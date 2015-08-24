import ConfigParser
import os
import pwd
import shutil
import sys
import subprocess
import tempfile

sys.path.insert(0, os.path.join(os.environ['CHARM_DIR'], 'lib'))

from charmhelpers.core.hookenv import charm_dir, config, log, relation_set, open_port, close_port
from charmhelpers.core.templating import render
from charmhelpers.fetch import giturl, apt_install, apt_update, archiveurl
from charmhelpers.core.host import service_restart, service_start, service_stop


PACKAGES = [ 'git', 'python-setuptools', 'python-dev', 'python-pip', 'apache2' ]

ZUUL_GIT_URL = 'https://github.com/openstack-infra/zuul.git'
ZUUL_USER = 'zuul'
ZUUL_CONF_DIR = '/etc/zuul'
ZUUL_SSH_DIR = '/home/zuul/.ssh'
ZUUL_SSH_PRIVATE_FILE = 'id_rsa'
ZUUL_RUN_DIR = '/var/run/zuul'
ZUUL_MERGER_RUN_DIR = '/var/run/zuul-merger'
ZUUL_STATE_DIR = '/var/lib/zuul'
ZUUL_GIT_DIR = '/var/lib/zuul/git'
ZUUL_LOG_DIR = '/var/log/zuul'

APACHE2_CONF_DIR = '/etc/apache2'

GEAR_GIT_URL = 'https://github.com/openstack-infra/gear.git'
GEAR_STABLE_TAG = '0.5.7'

OPENSTACK_FUNCTIONS_URL = 'https://raw.githubusercontent.com/' \
            'openstack-infra/project-config/master/zuul/openstack_functions.py'


def render_logging_conf():
    logging_conf = os.path.join(ZUUL_CONF_DIR, 'logging.conf')
    context = { 'zuul_log': os.path.join(ZUUL_LOG_DIR, 'zuul.log') }
    render('logging.conf', logging_conf, context, ZUUL_USER, ZUUL_USER)


def render_gearman_logging_conf():
    gearman_logging_conf = os.path.join(ZUUL_CONF_DIR, 'gearman-logging.conf')
    context = {
        'gearman_log': os.path.join(ZUUL_LOG_DIR, 'gearman-server.log')
    }
    render('gearman-logging.conf', gearman_logging_conf, context, ZUUL_USER,
        ZUUL_USER)


def render_zuul_conf():
    context = {
        'gearman_host': '0.0.0.0',
        'gearman_port': config('gearman-port'),
        'gearman_internal': 'true',
        'gearman_log': os.path.join(ZUUL_CONF_DIR, 'gearman-logging.conf'),
        'gerrit_server': config('gerrit-server'),
        'gerrit_port': '29418',
        'gerrit_username': config('username'),
        'gerrit_sshkey': os.path.join(ZUUL_SSH_DIR, ZUUL_SSH_PRIVATE_FILE),
        'zuul_layout': os.path.join(ZUUL_CONF_DIR, 'layout.yaml'),
        'zuul_logging': os.path.join(ZUUL_CONF_DIR, 'logging.conf'),
        'zuul_pidfile': os.path.join(ZUUL_RUN_DIR, 'zuul.pid'),
        'zuul_state_dir': ZUUL_STATE_DIR,
        'zuul_status_url': config('status-url'),
        'zuul_git_dir': ZUUL_GIT_DIR,
        'zuul_url': config('zuul-url'),
        'merger_git_user_email': config('git-user-email'),
        'merger_git_user_name': config('git-user-name'),
        'merger_pidfile': os.path.join(ZUUL_MERGER_RUN_DIR, 'merger.pid')
    }
    zuul_conf = os.path.join(ZUUL_CONF_DIR, 'zuul.conf')
    render('zuul.conf', zuul_conf, context, ZUUL_USER, ZUUL_USER)


def render_hyper_v_layout():
    layout_template = 'hyper-v/layout.yaml'
    if (config('vote-gerrit')):
        layout_template += '.vote'
    else:
        layout_template += '.nonvote'
    layout_conf = os.path.join(ZUUL_CONF_DIR, 'layout.yaml')
    render(layout_template, layout_conf, { }, ZUUL_USER, ZUUL_USER)


def render_zuul_vhost_conf():
    context = {
        'git_dir': ZUUL_GIT_DIR
    }
    zuul_vhost = os.path.join(APACHE2_CONF_DIR, 'sites-available/zuul.conf')
    render('apache2-vhost.conf', zuul_vhost, context, perms=0o644)


def download_openstack_functions():
    url_handler = archiveurl.ArchiveUrlFetchHandler()
    openstack_functions_path = os.path.join(ZUUL_CONF_DIR,
                                            'openstack_functions.py')
    url_handler.download(OPENSTACK_FUNCTIONS_URL, openstack_functions_path)
    zuul_user = pwd.getpwnam(ZUUL_USER)
    os.chown(openstack_functions_path, zuul_user.pw_uid, zuul_user.pw_gid)
    os.chmod(openstack_functions_path, 0644)


def create_zuul_upstart_services():
    zuul_server = '/etc/init/zuul-server.conf'
    zuul_merger = '/etc/init/zuul-merger.conf'
    zuul_server_bin = '/usr/local/bin/zuul-server'
    zuul_merger_bin = '/usr/local/bin/zuul-merger'
    zuul_conf = os.path.join(ZUUL_CONF_DIR, 'zuul.conf')

    context = {
        'zuul_server_bin': zuul_server_bin,
        'zuul_conf': zuul_conf,
        'zuul_user': ZUUL_USER
    }
    render('upstart/zuul-server.conf', zuul_server, context, perms=0o644)

    context.pop('zuul_server_bin')
    context.update({'zuul_merger_bin': zuul_merger_bin})
    render('upstart/zuul-merger.conf', zuul_merger, context, perms=0o644)


def install_from_git(repository_url, tag):
    current_dir = os.getcwd()

    temp_dir = tempfile.mkdtemp()
    git_handler = giturl.GitUrlFetchHandler()
    git_handler.clone(repository_url, temp_dir, 'master')

    os.chdir(temp_dir)
    subprocess.check_call(['git', 'checkout', 'tags/{0}'.format(tag)])
    subprocess.check_call(['pip', 'install', '-r', './requirements.txt'])
    subprocess.check_call(['python', './setup.py', 'install'])

    os.chdir(current_dir)
    shutil.rmtree(temp_dir)


def generate_zuul_ssh_key():
    zuul_user = pwd.getpwnam(ZUUL_USER)
    ssh_key = os.path.join(ZUUL_SSH_DIR, ZUUL_SSH_PRIVATE_FILE)
    with open(ssh_key, 'w') as f:
        f.write(config('ssh-key'))
    os.chown(ssh_key, zuul_user.pw_uid, zuul_user.pw_gid)
    os.chmod(ssh_key, 0600)


def update_zuul_conf():
    configs = config()
    services_restart = False

    if configs.changed('ssh-key'):
        generate_zuul_ssh_key()

    if configs.changed('vote-gerrit'):
        render_hyper_v_layout()
        services_restart = True

    configs_keys = ['gearman-port', 'gerrit-server', 'username', 'zuul-url',
                    'status-url', 'git-user-name', 'git-user-email' ]
    for key in configs_keys:
        if configs.changed(key):
            services_restart = True
            break
    if not services_restart:
        log("Zuul config values didn't change.")
        return False

    configs.save()
    render_zuul_conf()

    return services_restart


def configure_apache2():
    render_zuul_vhost_conf()

    # required apache2 modules
    subprocess.check_call(["a2enmod", "cgi"])
    subprocess.check_call(["a2enmod", "rewrite"])

    # disable default website
    subprocess.check_call(["a2dissite", "000-default"])

    # enable zuul website
    subprocess.check_call(["a2ensite", 'zuul'])

    service_restart('apache2')


# HOOKS METHODS

def install():
    apt_update(fatal=True)
    apt_install(PACKAGES, fatal=True)

    install_from_git(ZUUL_GIT_URL, config('version'))
    install_from_git(GEAR_GIT_URL, GEAR_STABLE_TAG)

    try:
        pwd.getpwnam(ZUUL_USER)
    except KeyError:
        # create Zuul user
        subprocess.check_call(["useradd", "--create-home", ZUUL_USER])

    directories = [ ZUUL_CONF_DIR, ZUUL_SSH_DIR, ZUUL_RUN_DIR, ZUUL_STATE_DIR,
                    ZUUL_GIT_DIR, ZUUL_LOG_DIR, ZUUL_MERGER_RUN_DIR ]
    zuul_user = pwd.getpwnam(ZUUL_USER)
    for directory in directories:
        if not os.path.exists(directory):
            os.mkdir(directory)
        os.chmod(directory, 0755)
        os.chown(directory, zuul_user.pw_uid, zuul_user.pw_gid)

    generate_zuul_ssh_key()

    # generate configuration files
    render_logging_conf()
    render_gearman_logging_conf()
    render_hyper_v_layout()
    render_zuul_conf()
    create_zuul_upstart_services()
    download_openstack_functions()

    configure_apache2()


def config_changed():
    if update_zuul_conf():
        # zuul.conf was updated and Zuul services must be restarted
        service_restart('zuul-server')
        service_restart('zuul-merger')
        log('Zuul services restarted')


def start():
    service_start('zuul-server')
    service_start('zuul-merger')
    log('Zuul services started.')


def stop():
    service_stop('zuul-server')
    service_stop('zuul-merger')
    log('Zuul services stopped.')


def zuul_relation_changed():
    gearman_port = config('gearman-port')
    relation_set(gearman_ip=unit_get('public-address'),
                 gearman_port=gearman_port)
    open_port(gearman_port)


def zuul_relation_broken():
    close_port(config('gearman-port'))

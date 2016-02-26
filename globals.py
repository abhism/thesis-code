import ConfigParser
import logging


guests = {}

host = None

#logging stuff
debuglogger = logging.getLogger('debug')
debuglogger.setLevel(logging.DEBUG)
fh = logging.FileHandler('monitor_debug.log')
formatter = logging.Formatter('%(asctime)s: %(levelname)8s: %(message)s')
fh.setFormatter(formatter)
debuglogger.addHandler(fh)


errorlogger = logging.getLogger('error')
errorlogger.setLevel(logging.WARN)
fh = logging.FileHandler('monitor_error.log')
ch = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s: %(levelname)8s: %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)
errorlogger.addHandler(fh)
errorlogger.addHandler(ch)


datalogger = logging.getLogger('data')
datalogger.setLevel(logging.INFO)
fh = logging.FileHandler('monitor_data.log')
formatter = logging.Formatter('%(asctime)s: %(levelname)8s: %(message)s')
fh.setFormatter(formatter)
datalogger.addHandler(fh)

# read config
config = ConfigParser.RawConfigParser()
try:
    config.read("config.ini")
except Exception as e:
    errorlogger.exception('Cannot read config, Exiting!')
    sys.exit(1)


# Nova stuff
nova_demo = None
nova_admin = None
if config.getboolean('nova', 'enabled'):
    from keystoneclient.auth.identity import v3
    from keystoneclient import session
    from keystoneclient.v3 import client
    auth_url = config.get('nova', 'auth_url')
    password = config.get('nova', 'demo_password')

    auth_demo = v3.Password(auth_url=auth_url,
                       username='demo',
                       password=password,
                       project_domain_name='defualt',
                       project_name='demo',
                       user_domain_name='default')

    sess_demo = session.Session(auth=auth_demo)
    keystone_demo = client.Client(session=sess_demo)


    password = config.get('nova', 'admin_password')
    auth_admin= v3.Password(auth_url=auth_url,
                       username='admin',
                       password=password,
                       project_domain_name='defualt',
                       project_name='admin',
                       user_domain_name='default')

    sess_admin= session.Session(auth=auth_admin)
    keystone_admin= client.Client(session=sess_admin)

    from novaclient import client
    nova_demo = client.Client(3, session=keystone_demo.session)
    nova_admin = client.Client(3, session=keystone_admin.session)

#etcd stuff
etcdClient = None
if config.getboolean('etcd', 'enabled'):
    import etcd
    host = config.get('etcd', 'host')
    port = config.getint('etcd', 'port') #default id 2379
    etcdClient = etcd.Client(host=host, port=port)


import socket
hostname = 'error'
try:
    hostname = socket.gethostname()
except Exception as e:
    errorlogger.exception('Could not determine hostname')

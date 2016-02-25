import ConfigParser
import logging

guests = {}

host = None

configDefaults = {}

config = ConfigParser.RawConfigParser()

#logging
debuglogger = logging.getLogger('debug')
debuglogger.setLevel(logging.DEBUG)
fh = logging.FileHandler('monitor_debug.log')
formatter = logging.Formatter('%(asctime)s: %(levelname)8s: %(message)s')
fh.setFormatter(formatter)
debuglogger.addHandler(fh)


errorlogger = logging.getLogger('error')
errorlogger.setLevel(logging.ERROR)
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



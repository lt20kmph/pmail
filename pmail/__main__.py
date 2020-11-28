import argparse
import textwrap
import os
import sys
from pmail.common import config, WORKING_DIR
from shutil import copyfile
import pmail.client
import pmail.server

if __name__ == '__main__':
  parser = argparse.ArgumentParser(
      prog='pmail',
      description='simple tui client for gmail',
      formatter_class=argparse.RawDescriptionHelpFormatter, epilog=textwrap.dedent('''\
pmail must be run with EITHER of the flags -m or -n to do something useful
if pmail is run with BOTH of -m and -n flags then it will exit with a warning
'''))

  parser.add_argument('-v', '--version', action='version',
                      version='%(prog)s ' + pmail.__version__)

  configDir = os.path.join(os.environ['HOME'], '.config', 'pmail')
  configPath = os.path.join(configDir, 'config.yaml')

  parser.add_argument('--mk-config',
                      help='Install an example file to: {}'
                      .format(configPath),
                      action='store_true')

  # parser.add_argument('-c',
  #                     # '--config',
  #                     metavar='PATH',
  #                     help='PATH=path/to/config.yaml',
  #                     # default='config.yaml',
  #                     action='store')

  parser.add_argument('-n',
                      metavar='ACCOUNT_ID',
                      choices=config.listAccountIds(),
                      help='return the number of unread messages for ACCOUNT_ID',
                      action='store')

  parser.add_argument('-m',
                      metavar='MODE',
                      choices=['server', 'client'],
                      help='run pmail in MODE=[server|client] mode',
                      action='store')

  # parser.add_argument('-t',
  #                     metavar='TEST',
  #                     # choices=['server', 'client'],
  #                     help='testing stuff',
  #                     action='store')

  args = parser.parse_args()

  if args.mk_config:
    if not os.path.exists(configPath):
      if not os.path.exists(configDir):
        os.makedirs(configDir)
      configSrc = os.path.join(WORKING_DIR, 'config.yaml')
      copyfile(configSrc, configPath)
      print('Config successfully installed at: {}.'
            .format(configPath))
    else:
      print('Config file already exists at: {}.'
            .format(configPath))
    sys.exit()

  if args.n is None and args.m is None:  # and args.t is None:
    parser.print_help()
  elif args.n and args.m:
    msg = 'pmail can only be run with ONE of -n or -m'
    raise argparse.ArgumentTypeError(msg)
  elif args.n:
    # print(account)
    pmail.server.checkForNewMessages(args.n)
    # print(args.n)
  elif args.m == 'client':
    pmail.client.start()
  elif args.m == 'server':
    pmail.server.start()
  # elif args.t == 'attach':
  #   pmail.common.setupAttachments('o.g.sargent@gmail.com')

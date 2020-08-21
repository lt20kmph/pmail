import argparse
import textwrap
import os
from pmail.common import config
import pmail.client
import pmail.server

if __name__ == '__main__':
  parser = argparse.ArgumentParser(prog='pmail',
                                   description='simple tui client for gmail',
                                   formatter_class=argparse.RawDescriptionHelpFormatter, epilog=textwrap.dedent('''\
pmail must be run with EITHER of the flags -m or -n to do something useful
if pmail is run with BOTH of -m and -n flags then it will exit with a warning
'''))

  parser.add_argument('-v', '--version', action='version',
                    version='%(prog)s ' + pmail.__version__)

  parser.add_argument('-c',
                      # '--config',
                      metavar='PATH',
                      help='PATH=path/to/config.yaml',
                      # default='config.yaml',
                      action='store')

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

  args = parser.parse_args()
  if args.c:
    pass
  else:
    if not os.path.exists(os.path.join(os.environ['HOME'],'.config/pmail')):
      os.makedirs(os.path.join(os.environ['HOME'],'.config/pmail'))
  if args.n == None and args.m == None:
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

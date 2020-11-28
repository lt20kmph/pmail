#!/usr/bin/python

# ---> Imports
from __future__ import print_function
from itertools import chain
import sys
from datetime import datetime, timezone
import os
import os.path
import re
import pickle
import logging
import yaml
from yaml import Loader
from sqlalchemy import create_engine  # desc, UniqueConstraint
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import sessionmaker, relationship, scoped_session
from sqlalchemy.ext.declarative import declarative_base
from googleapiclient.discovery import build
from googleapiclient.discovery_cache.base import Cache
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
# <---

# ---> Initial definitions

WORKING_DIR = os.path.dirname(os.path.abspath(__file__))


class Config():
  def __init__(self, **kwargs):
    try:
      home = os.environ['HOME']
    except KeyError as e:
      print(e)
      sys.exit()
    pmailDir = '.local/share/pmail'
    configDir = '.config/pmail'
    if 'config_path' not in kwargs:
      config_path_0 = os.path.join(home, configDir, 'config.yaml')
      config_path_1 = os.path.join(WORKING_DIR, 'config.yaml')
      if os.path.exists(config_path_0):
        config_path = config_path_0
      elif os.path.exists(config_path_1):
        config_path = config_path_1
      else:
        msg = "Could not find config file 'config.yaml'." +\
              "Pmail looked in {} and {}.\r\n"\
              .format(config_path_0, config_path_1)
        print(msg)
        sys.exit()
    else:
      config_path = kwargs.get('config_path')

    with open(config_path, 'r', encoding='utf-8') as f:
      y = yaml.load(f, Loader=Loader)
    b = y['behaviour']
    self.syncFrom = b['sync_from']
    self.editor = b['editor']
    self.pager = b['pager']
    self.picker = b['picker']
    self.afterUnreadChange = b.get('after_unread_change', None)
    tmpPath = os.path.join(home, pmailDir, 'tmp')
    if not os.path.exists(tmpPath):
      os.makedirs(tmpPath)
    self.tmpDir = b.get('tmp_directory', tmpPath)
    picklePath = os.path.join(home, pmailDir, 'pickles')
    if not os.path.exists(picklePath):
      os.makedirs(picklePath)
    self.pickleDir = b.get('pickle_directory', picklePath)
    dlPath = os.path.join(home, 'Downloads')
    if not os.path.exists(dlPath):
      os.makedirs(dlPath)
    self.dlDir = b.get('download_directory', dlPath)
    self.dbPath = b.get('db_path',
                        os.path.join(home, pmailDir, 'pmail.db'))
    self.logPath = b.get('log_path',
                         os.path.join(home, pmailDir, 'pmail.log'))

    logLevels = {'WARNING': logging.WARNING, 'INFO': logging.INFO}
    if b['log_level'] in logLevels.keys():
      self.logLevel = logLevels[b['log_level']]
    else:
      print('WARNING: log_level incorrectly configured, ' +
            '{} is not a valid level.\r\n'.format(b['log_level']))
      sys.exit()
    self.updatePolicy = b.get('update_policy', 'frequency')
    if self.updatePolicy not in ['frequency', 'pubsub']:
      print("WARNING: update_policy incorrectly configured, " +
            "update_policy must be one of 'pubsub' or 'frequency'/r/n")
      sys.exit()
    self.updateFreq = b['update_frequency']
    self.port = b['port_number']

    am = y['appearance']['markers']
    ac = y['appearance']['colors']
    self.unread = am['unread']
    self.attachment = am['attachment']
    self.user = am['user']
    self.seperator = am['seperator']
    self.fg = ac['fg']
    self.bg = ac['bg']
    self.hiFg = ac['highlighted_fg']
    self.hiBg = ac['highlighted_bg']
    self.selFg = ac['selected_fg']
    self.selBg = ac['selected_bg']
    self.stFg = ac['statusline_fg']
    self.stBg = ac['statusline_bg']

    self.accounts = y['accounts']

    self.dbExists = False

    global config
    config = self

  def listAccounts(self):
    return self.accounts.keys()

  def listAccountIds(self):
    return [self.accounts[k]['id'] for k in self.listAccounts()]

  def getName(self, myemail):
    return self.accounts[myemail]['name']

  def fzfArgs(self, prompt):
    return self.picker.split(' ') + ['--prompt', prompt]

  def w3mArgs(self):
    return self.pager.split(' ')

  def vimArgs(self, draftId):
    args = re.split('(-c)', self.editor)
    file = 'f ' + os.path.join(self.tmpDir, draftId)
    args = list(filter(lambda x: not x == '', map(lambda x: x.strip(), args)))
    args.append(file)
    return args


# Parse config file
config = Config()

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly',
          'https://www.googleapis.com/auth/gmail.send',
          'https://www.googleapis.com/auth/gmail.modify',
          'https://www.googleapis.com/auth/gmail.settings.basic']


class PubSubFilter(logging.Filter):
  """Keep pubsub spam out of the log."""

  def filter(self, record):
    if (record.module == 'bidi' or
        record.module == 'streaming_pull_manager') and\
       (record.msg.startswith('Observed ') or
            record.msg.startswith('Re-established stream')):
      return False
    return True


handler = logging.FileHandler(filename=config.logPath)

handler.addFilter(PubSubFilter())

logging.basicConfig(level=config.logLevel,
                    format='%(levelname)s::%(asctime)s::[%(module)s]: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S',
                    handlers=[handler])

logger = logging.getLogger(__name__)

DB_PATH = 'sqlite:///' + os.path.join(WORKING_DIR, config.dbPath)

HEADERS = ['From', 'Subject', 'To', 'Reply-To', 'In-Reply-To',
           'References', 'Message-ID', 'Content-Type']

engine = create_engine(DB_PATH)
Base = declarative_base(bind=engine)

session_factory = sessionmaker(bind=engine,
                               expire_on_commit=False)
Session = scoped_session(session_factory)

# <---

# ---> mkService


def mkService(account):
  '''
  Make a service object for use with the API.
  '''
  credentialsPath = config.accounts[account]['credentials']
  tokenPath = os.path.join(config.pickleDir, account.split('@')[0] + '.pickle')
  creds = None
  # The file *.pickle stores the user's access and refresh tokens, and is
  # created automatically when the authorization flow completes for the first
  # time.
  if os.path.exists(tokenPath):
    with open(tokenPath, 'rb') as token:
      creds = pickle.load(token)
  # If there are no (valid) credentials available, let the user log in.
  if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
      creds.refresh(Request())
    else:
      flow = InstalledAppFlow.from_client_secrets_file(
          credentialsPath, SCOPES)
      creds = flow.run_local_server(port=8686)
    # Save the credentials for the next run
    with open(tokenPath, 'wb') as token:
      pickle.dump(creds, token)

  service = build('gmail', 'v1', credentials=creds, cache=MemoryCache())
  return service

# <---

# ---> Formating functions


def formatSize(num):
  '''
  Format a filesize in bytes into a human readable
  one.
  '''
  for unit in ['B', 'K', 'M', 'G', 'T', 'P', 'E', 'Z']:
    if abs(num) < 1024.0:
      # return "%3.1f%s%s" % (num, unit, suffix)
      numString = "{:.1f}".format(num)
      lenNumString = len(numString)
      if lenNumString > 4:
        numString = numString[:4]
      elif lenNumString < 4:
        numString = numString + " " * (4 - lenNumString)
      return numString + unit
    num /= 1024.0
  # Unlikely to need this one!
  return "%.1f%s%s" % (num, 'Yi')


def unix2localTime(unix_timestamp):
  '''
  Convert timestamp to local time and format
  like e.g. Jun 3
  '''
  utc_time = datetime.fromtimestamp(int(unix_timestamp) // 1000, timezone.utc)
  local_time = utc_time.astimezone()
  return local_time.strftime("%b %d")


def unix2localTime2(unix_timestamp):
  '''
  Convert timestamp to local time and format like
  e.g. Mon, Jun 30, 2020 at 5.25 PM
  '''
  utc_time = datetime.fromtimestamp(int(unix_timestamp) // 1000, timezone.utc)
  local_time = utc_time.astimezone()
  return local_time.strftime("%a, %b %d, %Y at %-I.%M %p")

# <---

# ---> Class defintions


class MemoryCache(Cache):
  '''
  This is needed so that the cache is working inside Thread
  objects.
  '''
  _CACHE = {}

  def get(self, url):
    return MemoryCache._CACHE.get(url)

  def set(self, url, content):
    MemoryCache._CACHE[url] = content


class Attachments(Base):
  '''
  Store Attachments.
  '''
  __tablename__ = 'attachments'
  id = Column(Integer, primary_key=True)
  messageId = Column(String, ForeignKey('header_info.messageId'))
  partId = Column(String)
  filename = Column(String)
  contentType = Column(String)
  size = Column(Integer)

  def __init__(self, messageId, partId, filename, contentType, size):
    self.messageId = messageId
    self.partId = partId
    self.filename = filename
    self.contentType = contentType
    self.size = size

  def display(self):
    '''
    Display information about the attachment.
    '''
    contentType = self.contentType
    if len(contentType) > 20:
      contentType = contentType[:20]
    elif len(contentType) < 20:
      contentType = contentType + ' ' * (20 - len(contentType))
    display = '{} {} ({}) {}'.format(
        self.partId,
        contentType,
        formatSize(self.size),
        self.filename)
    return display


class AddressBook(Base):
  '''
  Store address in a seperate table so that it can be queried
  quickly rather than an expensive query on the MessageInfo
  table every time it is needed.
  '''
  __tablename__ = 'address_book'
  account = Column(String, ForeignKey('user_info.emailAddress'),
                   primary_key=True)
  address = Column(String, primary_key=True)

  def __init__(self, account, address):
    self.account = account
    self.address = address

  @classmethod
  def mk(cls, account, session, message):
    '''
    Method to scour for email address in the MessageInfo table
    and sort them into uniques and add to the AddressBook table
    '''
    q = session.query(cls).filter(cls.account == account)

    addresses = [a.address for a in q]
    newAddresses = set()

    sender = message.sender.lower().strip()
    if sender not in addresses:
      newAddresses.add(sender)
    try:
      all = filter(lambda x: not re.search(account, x),
                   (message.recipients).split(','))
      for a in all:
        address = a.lower().strip()
        if address not in addresses:
          newAddresses.add(address)
    except Exception:
      logger.exception('Something bad happened trying to add new addresses.')

    # s.query(cls).filter(cls.account == account).delete()
    # s.commit()
    try:
      session.add_all([cls(account, a) for a in newAddresses])
      session.commit()
    except Exception:
      logger.exception(
          'Something bad happened trying to commit new addresses.')

  @classmethod
  def addressList(cls, account):
    session = Session()
    q = session.query(cls).filter(cls.account == account)
    Session.remove()
    for address in q:
      yield address.address


class UserInfo(Base):
  '''
  Store Profile information for each account.
  '''
  # TODO: Review this, num of unreads not being used? should i update?
  __tablename__ = 'user_info'
  emailAddress = Column(String, primary_key=True)
  totalMessages = Column(Integer)
  totalThreads = Column(Integer)
  historyId = Column(Integer)
  numOfUnreadMessages = Column(Integer)
  shouldIupdate = Column(Boolean)
  watchExpirey = Column(Integer)
  # token = Column(String)
  messages = relationship('MessageInfo', backref='user_info',
                          cascade='all, delete, delete-orphan')
  addressBook = relationship('AddressBook', backref='user_info',
                             cascade='all, delete, delete-orphan')

  def __init__(self, account):
    self.emailAddress = account
    self.totalMessages = None
    self.totalThreads = None
    self.historyId = None
    self.numOfUnreadMessages = None
    self.shouldIupdate = True
    self.watchExpirey = None

  @staticmethod
  def _numOfUnreadMessages(session, account):
    '''
    Get the number of unread messages in the INBOX.

    Args:
      account: The account to query.
    Returns: An integer.
    '''
    q1 = session.query(Labels.messageId).filter(Labels.labelId == 'UNREAD')
    q2 = session.query(Labels.messageId).filter(Labels.labelId == 'INBOX')
    q = session.query(MessageInfo).filter(
        MessageInfo.emailAddress == account,
        MessageInfo.messageId.in_(q1),
        MessageInfo.messageId.in_(q2))
    count = q.count()
    return count

  @classmethod
  def succesfulUpdate(cls, session, account):
    q = session.query(cls).get(account)
    q.shouldIupdate = False
    session.commit()

  def update(self, session, account, service, lastHistoryId):
    '''
    Method to update UserInfo.

    Args:
      account: emailAddress for which we are updating info.
      session: A DB session
      service: API service. Possibly None, in this case we only update
      numOfUnreadMessages and possibly the lastHistoryId.
      lastHistoryId: The history id from the last time the db was updated.
      Possibly None, in which case do not update!
    '''
    numOfUnreadMessages = self._numOfUnreadMessages(session, account)
    self.numOfUnreadMessages = numOfUnreadMessages
    if service:
      profile = service.users().getProfile(userId='me').execute()
      messagesTotal = profile['messagesTotal']
      threadsTotal = profile['threadsTotal']
      self.totalMessages = messagesTotal
      self.totalThreads = threadsTotal

    self.historyId = lastHistoryId
    session.commit()


def setupAttachments(account):
  '''
  Creates a new label with id = name = 'ATTACHMENT'.
  Adds this lable to all messages with attachments.
  Makes filter to add this label to incoming mail.
  '''
  attachmentLabel = {
      'labelListVisibility': 'labelHide',
      'messageListVisibility': 'hide',
      'type': 'user',
      'name': 'ATTACHMENT',
  }

  service = mkService(account)
  labels = service.users().labels().list(userId='me').execute()['labels']
  if 'ATTACHMENT' not in [label['name'] for label in labels]:
    response = service.users().labels().create(
        userId='me', body=attachmentLabel).execute()
    labelId = response['id']
  else:
    labelId = [label['id'] for label in labels
               if label['name'] == 'ATTACHMENT'][0]
  ids = listMessagesMatchingQuery(service, account, query='has:attachment')
  # labels = [(id, 'ATTACHMENT') for id in ids]
  # Labels.addLabels(session, labels)
  chunkedIds = [ids[i:i + 1000]
                for i in range(0, int(len(ids) / 1000) + 1, 1000)]
  for chunk in chunkedIds:
    # print(chunk)
    modify = {
        "addLabelIds": [labelId],
        "ids": [c['id'] for c in chunk]
    }
    response = service.users().messages()\
        .batchModify(userId='me', body=modify).execute()

  attachmentFilter = {
      "action": {
          "addLabelIds": [labelId],
      },
      "criteria": {
          "hasAttachment": True
      }
  }

  currentFilters = service.users().settings().filters()\
      .list(userId='me').execute()

  for f in currentFilters['filter']:
    if 'addLabelIds' in f['action'].keys()\
            and 'hasAttachment' in f['criteria'].keys()\
            and labelId in f['action']['addLabelIds']\
            and f['criteria']['hasAttachment']:
      # print('filter exists')
      break
  else:
    service.users().settings().filters().create(
        userId='me', body=attachmentFilter
    ).execute()


class LabelInfo(Base):
  '''
  Store information about labels.
  Correspondance name - id.
  '''
  __tablename__ = 'label_info'
  labelId = Column(String, primary_key=True)
  labelAccount = Column(String, primary_key=True)
  labelName = Column(String)

  def __init__(self, account, labelId, labelName):
    self.labelId = labelId
    self.labelAccount = account
    self.labelName = labelName

  @classmethod
  def addLabels(cls, session, account):
    '''
    Gets labelInfo from google and stores it.

    Args:
      session: A DB session.
      account: Account for which info to get.

    Returns: None.
    '''
    service = mkService(account)
    response = service.users().labels().list(userId='me').execute()['labels']
    for label in response:
      q = session.query(cls)\
          .filter(cls.labelId == label['id'])\
          .filter(cls.labelAccount == account)\
          .first()
      if q is None:
        labelInfo = cls(account, label['id'], label['name'])
        session.add(labelInfo)
    # TODO: remove old labels...
    # q = session.query(cls)\
    #     .filter(~cls.labelId.in_([label['id'] in response]))\
    #     .delete(synchronize_session=False)
    session.commit()

  @classmethod
  def getName(cls, session):
    labelMap = {}
    for account in config.listAccounts():
      q = session.query(cls).filter(cls.labelAccount == account)
      labelMap[account] = {label.labelId: label.labelName for label in q}
    return labelMap


class Labels(Base):
  '''
  Store Labels attached to messages.
  '''
  __tablename__ = 'labels'
  id = Column(Integer, primary_key=True)
  messageId = Column(String, ForeignKey('header_info.messageId'))
  labelId = Column(String, ForeignKey('label_info.labelId'))
  # labelId = Column(String)
  # labelName = Column(String)

  def __init__(self, messageId, labelId):
    self.messageId = messageId
    self.labelId = labelId
    # self.labelId = labelId
    # self.labelName = labelName

  @classmethod
  def addLabels(cls, session, labels):
    '''
    Add labels to messages.

    Args:
      session: A DB session.
      labels: A list of pairs (m,ls) where m is a message
      id and ls is a list of labels to add to the message.

    Returns: None.
    '''
    for (messageId, ls) in labels:
      for label in ls:
        session.add(cls(messageId, label))
        session.commit()

  @classmethod
  def removeLabels(cls, session, labels):
    '''
    Remove labels from messages.

    Args:
      session: A DB session.
      labels: A list of pairs (m,ls) where m is a message
      id and ls is a list of labels to add to the message.

    Returns: None.
    '''
    for (messageId, ls) in labels:
      session.query(cls)\
          .filter(cls.messageId == messageId, cls.labelId.in_(ls))\
          .delete(synchronize_session=False)
      # logger.info('About to commit, after removing labels.')
    session.commit()
    logger.info('Committed, after removing labels.')
    if 'UNREAD' in chain(*[ls for (messageId, ls) in labels]) and\
            config.afterUnreadChange:
      os.system(config.afterUnreadChange)

# ---> MessageInfo class


class MessageInfo(Base):
  '''
  Big class for storing information about an email
  '''
  __tablename__ = 'header_info'
  messageId = Column(String, primary_key=True)
  emailAddress = Column(String, ForeignKey('user_info.emailAddress'))
  historyId = Column(String)
  time = Column(String, index=True)
  size = Column(Integer)
  snippet = Column(String)
  externalId = Column(String)
  subject = Column(String)
  sender = Column(String)
  replyTo = Column(String)
  inReplyTo = Column(String)
  references = Column(String)
  recipients = Column(String)
  contentType = Column(String)
  hasAttachments = Column(Boolean)
  labels = relationship('Labels', backref='header_info',
                        cascade="all, delete, delete-orphan",
                        lazy='subquery')
  attachments = relationship('Attachments', backref='header_info',
                             cascade="all, delete, delete-orphan")

  def __init__(self, messageId, emailAddress, historyId, time, size,
               snippet, externalId, subject, sender, replyTo, inReplyTo,
               references, recipients, contentType):
    self.messageId = messageId
    self.emailAddress = emailAddress
    self.historyId = historyId
    self.time = time
    self.size = size
    self.snippet = snippet
    self.externalId = externalId
    self.subject = subject
    self.sender = sender
    self.replyTo = replyTo
    self.inReplyTo = inReplyTo
    self.references = references
    self.recipients = recipients
    self.contentType = contentType

  def __eq__(self, other):
    if isinstance(other, self.__class__):
      return self.messageId == other.messageId
    else:
      return False

  def __ne__(self, other):
    return not self.__eq__(other)

  def display(self, senderWidth, scrWidth, labelMap):
    '''
    For displaying information about a message in the main screen
    of the program.
    Args:
      senderWidth: How wide should the sender column be.
      scrWidth: How wide is the screen.

    Reurns:
      A formatted string.
    '''
    if 'UNREAD' in [label.labelId for label in self.labels]:
      marker = chr(config.unread) + ' '
    else:
      marker = '  '
    if self.existsAttachments(labelMap):
      attachment = chr(config.attachment) + ' '
    else:
      attachment = '  '
    str = ' {} {} {} ({}) {} {}'.format(
        marker,
        unix2localTime(self.time),
        self.formatName(senderWidth),
        formatSize(self.size),
        attachment,
        self.subject,
        ' ' * scrWidth
    )[:scrWidth]
    return str

  def showLabels(self, labelMap):
    return [labelMap[self.emailAddress][label.labelId] 
            for label in self.labels]

  def timeForReply(self):
    '''
    Returns the formatted time for use in the extra line of
    information inserted at the top of replies.
    '''
    return unix2localTime2(self.time)

  def parseSender(self):
    '''
    Try to extract name and email address from the 'From'
    field of the header.
    '''
    try:
      email = re.search('\<(.*?)\>', self.sender).group(1)
    except AttributeError:
      email = self.sender
    except Exception:
      logger.exception('An unexpected error occurred trying to parse sender.')
    name = re.sub(' \<(.*?)\>', '', self.sender)
    return email, name

  def formatName(self, senderWidth):
    name = self.parseSender()[1]
    name = re.sub('"', '', name)
    if len(name) < senderWidth:
      name = name + ' ' * (senderWidth - len(name))
    else:
      name = name[:senderWidth]
    return name

  def existsAttachments(self, labelMap):
    '''
    Try to figure out if there are attachments from the content-type
    header. This can return false positives.
    To deal with this if at some later stage (usually, when trying to view
    attachments) it is found that really there were no attachments, the
    hasAttachments attribute gets updated to False.
    if self.hasAttachments == False:
      return self.hasAttachments
    else:
      try:
        s = re.search('multipart/mixed', self.contentType)
      except Exception:
        logger.exception('Handle this exception better!-2')
        s = False
      if s == None:
        return False
      else:
        return True
    '''
    labelIds = [label.labelId for label in self.labels]
    labelNames = [labelMap[self.emailAddress][label] for label in labelIds]
    return 'ATTACHMENT' in labelNames

  @classmethod
  def addMessage(cls, account, session, msg):
    '''
    Add a message to the db.
    Args:
      account: Account which owns the message.
      session: A db session.
      msg: The message to add.
    '''
    headers = dict(zip(HEADERS, [None for i in range(len(HEADERS))]))
    for h in msg['payload']['headers']:
      name = h['name']
      for n in HEADERS:
        if name.lower() == n.lower():
          headers[n] = h['value']

    try:
      labels = [Labels(msg['id'], label) for label in msg['labelIds']]
      session.add_all(labels)
    except KeyError:
      logger.debug('Could not add: ' + str(msg))
      logger.debug("Adding label ['UNCLASSIFIED']")
      session.add(Labels(msg['id'], 'UNCLASSIFIED'))
    except Exception:
      logger.exception('Something bad happened while trying to add messages.')
    if headers['From']:
      header = cls(
          msg['id'],
          account,
          msg['historyId'],
          msg['internalDate'],
          msg['sizeEstimate'],
          msg['snippet'],
          headers['Message-ID'],
          headers['Subject'],
          headers['From'],
          headers['Reply-To'],
          headers['In-Reply-To'],
          headers['References'],
          headers['To'],
          headers['Content-Type'])
      session.add(header)
      # logger.debug('Adding header to db')
      return header
    else:
      logger.debug(str(headers))
      logger.debug(str(msg))
      return None

  @classmethod
  def addMessages(cls, session, account, service, messageIds):
    '''
    Add many messages to the db.

    Args:
      session: A db session.
      account: The accoun which owns the messages
      service: An API service.
      messageIds: List of message ids which we are going to add.
    '''
    def doesMessageAlreadyExist(messageId):
      q = session.query(cls).filter(cls.messageId == messageId)
      if q.first():
        return False
      else:
        return True

    def _updateDb(session, account, requestId, response, exception):
      '''
      Helper function for batch requests.

      Args:
        session: A DB session.
        account: The account which the messages belong to.
        requestId: Id of the request.
        response: Response of the request (If succesful, this is the message)
        exception: An exception if something went wrong.
      '''
      if exception is not None:
        logger.exception('There was an Error while trying to update db.')
        # Do something with the exception
        # See BatchHttpRequest docs
      else:
        # Parse headers.
        message = cls.addMessage(account, session, response)
        if message:
          AddressBook.mk(account, session, message)

    q = list(filter(doesMessageAlreadyExist, messageIds))
    i, l, batch = 0, len(q), service.new_batch_http_request()
    # logger.debug('Making batch request..')

    while i < l:
      for messageId in q[i:i + 100]:
        batch.add(service.users().messages().get(
            userId='me',
            id=messageId,
            format='metadata',
            metadataHeaders=HEADERS
        ), callback=(lambda x, y, z: _updateDb(session, account, x, y, z)))
      batch.execute()
      batch = service.new_batch_http_request()
      i += 100
    session.commit()

  @classmethod
  def removeMessages(cls, session, messageIds):
    '''
    Delete messages (Not in use currently and
    might need extra scopes to work.)
    '''
    session.query(cls).filter(cls.messageId in
                              messageIds).delete(synchronize_session=False)

# <---

# <---

# ---> Getting message Id's from Google


def listMessagesMatchingQuery(service, user_id, query=''):
  """List all Messages of the user's mailbox matching the query.

  Args:
    service: Authorized Gmail API service instance.
    user_id: User's email address. The special value "me"
    can be used to indicate the authenticated user.
    query: String used to filter messages returned.
    Eg.- 'from:user@some_domain.com' for Messages from a particular sender.

  Returns:
    List of Messages that match the criteria of the query. Note that the
    returned list contains Message IDs, you must use get with the
    appropriate ID to get the details of a Message.
  """
  try:
    response = service.users().messages().list(userId=user_id,
                                               q=query).execute()
    messages = []
    if 'messages' in response:
      messages.extend(response['messages'])

    while 'nextPageToken' in response:
      page_token = response['nextPageToken']
      response = service.users().messages().list(userId=user_id, q=query,
                                                 pageToken=page_token).execute()
      messages.extend(response['messages'])

    return messages
  except Exception:
    logger.exception('Error trying to list messages mathching a query.')

# <---

# ---> Find information


def countAttachments(message):
  c = 0
  if 'payload' in message:
    if 'parts' in message['payload']:
      for part in message['payload']['parts']:
        if part['filename']:
          c += 1
      return c
    else:
      return 0
  else:
    return 0


def myEmail(service):
  return (service.users().getProfile(userId='me').execute())['emailAddress']


# <---

# Only needed to create table structure
Base.metadata.create_all()

if __name__ == '__main__':
  pass

"""
vim:foldmethod=marker foldmarker=--->,<---
"""

#!/usr/bin/python

# ---> Imports
from __future__ import print_function
import sys
from datetime import datetime, timezone
import os
import os.path
import re
import pickle
import logging
import yaml
from yaml import Loader
from sqlalchemy import create_engine, desc, UniqueConstraint
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
  def __init__(self,config='config.yaml'):
    configpath = os.path.join(WORKING_DIR,config)
    with open(configpath, 'r', encoding='utf-8') as f:
      y = yaml.load(f, Loader=Loader)
    b = y['behaviour']
    self.syncFrom = b['sync_from']
    self.editor = b['editor']
    self.pager = b['pager']
    self.picker = b['picker']
    self.tmpDir = b['tmp_directory']
    self.pickleDir = b['pickle_directory']
    self.dlDir = b['download_directory']
    self.dbPath = b['db_path']
    self.logLevel = b['log_level']
    self.logPath = b['log_path']
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

  def listAccounts(self):
    return self.accounts.keys()

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


DB_PATH = 'sqlite:///' + WORKING_DIR + '/' + config.dbPath

HEADERS = ['From', 'Subject', 'To', 'Reply-To', 'In-Reply-To',
           'References', 'Message-ID', 'Content-Type']

logging.basicConfig(filename=os.path.join(WORKING_DIR, config.logPath),
                    level=logging.CRITICAL,
                    format='%(asctime)s :: %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

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
      creds = flow.run_local_server(port=0)
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
  utc_time = datetime.fromtimestamp(int(unix_timestamp)//1000, timezone.utc)
  local_time = utc_time.astimezone()
  return local_time.strftime("%b %d")


def unix2localTime2(unix_timestamp):
  '''
  Convert timestamp to local time and format like
  e.g. Mon, Jun 30, 2020 at 5.25 PM
  '''
  utc_time = datetime.fromtimestamp(int(unix_timestamp)//1000, timezone.utc)
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
    except:
      pass

    # s.query(cls).filter(cls.account == account).delete()
    # s.commit()
    try:
      session.add_all([cls(account,a) for a in newAddresses])
      session.commit()
    except:
      logger.info('Something went wrong trying to add new addresses.')

  @classmethod
  def addressList(cls,account):
    session = Session()
    q = session.query(cls).filter(cls.account == account)
    Session.remove()
    for address in q:
      yield address.address


class UserInfo(Base):
  '''
  Store Profile information for each account.
  '''
  __tablename__ = 'user_info'
  emailAddress = Column(String, primary_key=True)
  totalMessages = Column(Integer)
  totalThreads = Column(Integer)
  historyId = Column(Integer)
  numOfUnreadMessages = Column(Integer)
  shouldIupdate = Column(Boolean)
  # token = Column(String)
  messages = relationship('MessageInfo', backref='user_info',
                          cascade='all, delete, delete-orphan')
  addressBook = relationship('AddressBook', backref='user_info',
                             cascade='all, delete, delete-orphan')

  def __init__(self, emailAddress, totalMessages, totalThreads, historyId,
               numOfUnreadMessages):
    self.emailAddress = emailAddress
    self.totalMessages = totalMessages
    self.totalThreads = totalThreads
    self.historyId = historyId
    self.numOfUnreadMessages = numOfUnreadMessages
    self.shouldIupdate = True


  @staticmethod
  def _numOfUnreadMessages(session, account):
    '''
    Get the number of unread messages in the INBOX.

    Args:
      account: The account to query.
    Returns: An integer.
    '''
    q1 = session.query(Labels.messageId).filter(Labels.label == 'UNREAD')
    q2 = session.query(Labels.messageId).filter(Labels.label == 'INBOX')
    q = session.query(MessageInfo).filter(
        MessageInfo.emailAddress == account,
        MessageInfo.messageId.in_(q1),
        MessageInfo.messageId.in_(q2))
    count = q.count()
    return count

  @classmethod
  def update(cls, session, account, service, lastHistoryId):
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
    numOfUnreadMessages = cls._numOfUnreadMessages(session, account)
    q = session.query(cls).get(account)
    if service:
      profile = service.users().getProfile(userId='me').execute()
      messagesTotal = profile['messagesTotal']
      threadsTotal = profile['threadsTotal']
      # historyId = profile['historyId']
      if q:
        q.messagesTotal = messagesTotal
        q.threadsTotal = threadsTotal
        q.historyId = lastHistoryId
        q.numOfUnreadMessages = numOfUnreadMessages
      else:
        userInfo = cls(account, messagesTotal, threadsTotal, lastHistoryId,
                   numOfUnreadMessages)
        session.add(userInfo)
    elif q:
      q.numOfUnreadMessages = numOfUnreadMessages
      if lastHistoryId:
        q.historyId = lastHistoryId
    session.commit()


class Labels(Base):
  '''
  Store Labels attached to messages.
  '''
  __tablename__ = 'labels'
  id = Column(Integer, primary_key=True)
  messageId = Column(String, ForeignKey('header_info.messageId'))
  label = Column(String)

  def __init__(self, messageId, label):
    self.messageId = messageId
    self.label = label

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
      for l in ls:
        label =cls(messageId, l)
        session.add(label)
        session.commit()

  @classmethod
  def removeLabels(cls, session, labels):
    '''
    Remove labels to messages.

    Args:
      session: A DB session.
      labels: A list of pairs (m,ls) where m is a message
      id and ls is a list of labels to add to the message.

    Returns: None.
    '''
    for (messageId, ls) in labels:
      session.query(cls).filter(cls.messageId == messageId,cls.label.in_(ls))\
          .delete(synchronize_session='fetch')
      session.commit()

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

  def display(self, senderWidth, scrWidth):
    '''
    For displaying information about a message in the main screen
    of the program.
    Args:
      senderWidth: How wide should the sender column be.
      scrWidth: How wide is the screen.

    Reurns:
      A formatted string.
    '''
    try:
      if m.read == True:
        marker = '  '
      elif m.read == False:
        marker = chr(config.unread) + ' '
    except:
      if 'UNREAD' in [l.label for l in self.labels]:
        marker = chr(config.unread) + ' '
      else:
        marker = '  '
    if self.existsAttachments():
      attachment =chr(config.attachment) + ' '
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

  def showLabels(self):
    return [l.label for l in self.labels]

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
    except:
      email = self.sender
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

  def existsAttachments(self):
    '''
    Try to figure out if there are attachments from the content-type
    header. This can return false positives. 
    To deal with this if at some later stage (usually, when trying to view 
    attachments) it is found that really there were no attachments, the 
    hasAttachments attribute gets updated to False.
    '''
    if self.hasAttachments == False:
      return self.hasAttachments
    else:
      try:
        s = re.search('multipart/mixed', self.contentType)
      except:
        s = False
      if s == None:
        return False
      else:
        return True

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
    if headers['From']:
      header =cls(
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
        logger.debug(exception)
        # Do something with the exception
        # See BatchHttpRequest docs
      else:
        # Parse headers.
        message = cls.addMessage(account, session, response)
        if message:
          AddressBook.mk(account, session, message)
        
    q = list(filter(doesMessageAlreadyExist, messageIds))
    i, l, batch = 0, len(q), service.new_batch_http_request()
    logger.debug('Making batch request..')

    while i < l:
      for messageId in q[i:i+100]:
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
  except:
    print('An error occurred')

# <---

# ---> Db update functions



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


"""
vim:foldmethod=marker foldmarker=--->,<---
"""

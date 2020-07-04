#!/usr/bin/python

# ---> Imports
import base64
import curses
import email
import errno
import os

from apiclient import errors
from common import (mkService, s, Labels, MessageInfo, Attachments,
        ListMessagesMatchingQuery, removeLabels, addLabels, Session, logger,
        UserInfo, addMessages)
from sendMail import (sendMessage, mkSubject, createMessage)
from subprocess import run, PIPE, Popen
from threading import Thread
from uuid import uuid4
# <---

# ---> Helper functions
def listFiles(directory):
    for root, _, files in os.walk(directory):
        for f in files:
            yield os.path.join(root, f)

def __getHeaders(query, position, height, excludedLabels=[],
    includedLabels=[], count=False):
  excludeQuery = s.query(Labels.messageId).filter(
      Labels.label.in_(excludedLabels))
  includeQuery = s.query(Labels.messageId).filter(
      Labels.label.in_(includedLabels))
  q = query\
      .filter(~MessageInfo.messageId.in_(excludeQuery))\
      .filter(MessageInfo.messageId.in_(includeQuery))\
      .order_by(MessageInfo.time.desc())
  if count == False:
    return [h for h in q.slice(position, position+height-2)]
  elif count == True:
    return q.count()

'''
def _getHeaders(query, excludedLabels, includedLabels):
  excludeQuery = s.query(Labels.messageId).filter(
      Labels.label.in_(excludedLabels))
  includeQuery = s.query(Labels.messageId).filter(
      Labels.label.in_(includedLabels))
  q = query\
      .filter(~MessageInfo.messageId.in_(excludeQuery))\
      .filter(MessageInfo.messageId.in_(includeQuery))\
      .order_by(MessageInfo.time.desc())
  return [h for h in q]


def getHeaders(excludedLabels=['SPAM', 'TRASH'], includedLabels=['INBOX']):
  return _getHeaders(s.query(MessageInfo), excludedLabels, includedLabels)
'''

def readMessage(service, messageId):
  msg = service.users().messages().get(
      userId='me', id=messageId, format='raw').execute()
  msg = msg['raw']
  msg = base64ToString(msg).decode('utf-8')
  msg = email.message_from_string(msg, policy=email.policy.default)
  return msg.get_body(('html', 'plain',)).get_content()


def base64ToString(b):
  return base64.urlsafe_b64decode(b)


# <---

# ---> Curses functions


def setEscDelay():
  os.environ.setdefault('ESCDELAY', '25')


def getInput(stdscr, prompt, height, width):
  address = ""
  k, p = 0, len(prompt)
  stdscr.addstr(height-1, 0, ' ' * (width-1))
  stdscr.refresh()
  curses.curs_set(1)
  while k != '\n':
    l = len(address)
    stdscr.addstr(height-1, 0, prompt + address)
    stdscr.addstr(height-1, l + p, ' ' * (width - 1 - l - p))
    stdscr.move(height-1, p + l)
    stdscr.refresh()
    k = stdscr.getkey()
    if (k == 'KEY_BACKSPACE'):
      try:
        address = address[:l-1]
      except:
        pass
    elif (len(k) == 1) and (k != '\t'):
      if ord(k) == 27:
        return None
      else:
        address += k
  return address[:-1]


class StatusBarInfo():
  def __init__(self, currentAccount, includedLabels,
              excludedLabels, selectedHeader, searchTerms,
              numOfHeaders, totalMessages, currentMessageIndex,
              showLabels):
     self.currentAccount = currentAccount
     self.includedLabels = includedLabels
     self.excludedLabels = excludedLabels
     self.selectedHeader = selectedHeader
     self.searchTerms = searchTerms
     self.numOfHeaders = numOfHeaders
     self.totalMessages = totalMessages
     self.currentMessageIndex = currentMessageIndex
     self.showLabels = showLabels

  def mkStatusBar(self, stdscr, height, width):
    user = ' \uf007 '
    seperator = '\uf054'
    lUser = len(user) 

    account = ' {} {} {} '.format(
        seperator,
        self.currentAccount,
        seperator)
    acLen = len(account) + lUser
   
    if self.searchTerms:
      st = '?[{}] {} '.format(
          self.searchTerms,
          seperator)
    else:
      st = ''
    stLen = len(st)

    mb = self.includedLabels[0]
    mbLen = len(mb)

    numOfMessages = ' {} [{}/{} messages]'.format(
        seperator,
        self.currentMessageIndex,
        self.numOfHeaders)
    n = len(numOfMessages)

    if self.showLabels == True:
      labels = str(self.selectedHeader.showLabels())
    else:
      labels = ''
    labelsLen = len(labels)

    whitespace = ' {}'.format(
        ' ' * (width - mbLen - acLen - stLen - n - 1))

    stdscr.attron(curses.color_pair(35))
    stdscr.attron(curses.A_BOLD)
    stdscr.addstr(height - 2, 0, user)
    stdscr.attroff(curses.A_BOLD)

    stdscr.addstr(height - 2, lUser, account)

    stdscr.addstr(height - 2, acLen, st)

    stdscr.attron(curses.A_BOLD)
    stdscr.addstr(height - 2, acLen + stLen, mb)
    stdscr.attroff(curses.A_BOLD)

    stdscr.addstr(height - 2,acLen + stLen + mbLen, numOfMessages)

    stdscr.addstr(height - 2,acLen + stLen + mbLen + n, labels)

    stdscr.addstr(height - 2, acLen + stLen + mbLen + n + labelsLen, whitespace)
    stdscr.attroff(curses.color_pair(35))

    if self.numOfHeaders > 0:
      snippet = ' On {} <{}> wrote: {} {}'.format(
          self.selectedHeader.timeForReply(),
          self.selectedHeader.parseSender()[0],
          self.selectedHeader.snippet,
          ' ' * width
          )
      stdscr.addstr(height-1,0,snippet[:width-1])


''' probbaly won't include this
def showSnippet(stdscr, height, width, snippet):
  k = 0
  while k != ord('q'):
    height, width = stdscr.getmaxyx()
    w = min(80 + width % 2, width - 2)
    indent = (width - w)//2
    lines = wrap(snippet, width=(w - 2))
    top = (height - len(lines))//2
    for i, l in enumerate(lines):
      stdscr.attron(curses.color_pair(25))
      stdscr.addstr(top+i, indent, ' ' + l + ' ')
      ln = len(l)
      stdscr.addstr(top+i, indent + ln + 2, ' '*(w - ln - 2))
      stdscr.attroff(curses.color_pair(25))
    stdscr.refresh()
    k = stdscr.getch()


def search(results,excludedLabels,includedLabels):
    return _getHeaders(results,excludedLabels,includedLabels) 
'''

def _search(searchTerms):
  service = mkService()
  messageIds = [m['id'] for m in
          ListMessagesMatchingQuery(service,'me',query=searchTerms)]
  addMessages(s,service, messageIds)
  q = s.query(MessageInfo).filter(MessageInfo.messageId.in_(messageIds))
  s.commit()
  return q

def putMessage(stdcr, height, width, message):
  line = (":: " + message + ' ' * width)[:width - 1]
  stdcr.addstr(height - 1,0,line)


def drawConfirmationScreen(stdscr, myemail, state):
  k = 0
  curses.start_color()
  curses.use_default_colors()
  for i in range(16):
    curses.init_pair(i, i, -1)
  for i in range(16, 32):
    curses.init_pair(i, i - 16, 3)
  for i in range(32, 48):
    curses.init_pair(i, i - 32, 15)

  attachments = [] 
  while 1:
    if k == ord('q'):
      # Don't send.
      state['action'] = 'DO_NOT_SEND'
      return state 

    elif k == ord('y'):
      # Send.
      state['action'] = 'SEND'
      if len(attachments) > 0:
        state['attachments'] = attachments
      else:
        state['attachments'] = None
      return state

    elif k == ord('a'):
      # Add attachments.
      # state['action'] = 'ADD_ATTACHMENTS'
      home = os.environ.get('HOME')
      attachments.append(chooseAttachment(home))
      stdscr.clear()
      stdscr.refresh()
      with open(TMPDIR_WINDOW + 'stdscr.window','rb') as f:
        stdscr = curses.getwin(f) 
      stdscr.refresh()
      # return state

    elif k == ord('c'):
      # Add recipients.
      # Either To, Bcc, or Cc
      pass

    elif k == ord('s'):
      # Edit subject.
      pass 

    elif k == ord('t'):
      # Edit recipient.
      pass

    height, width = stdscr.getmaxyx()
    l = len(attachments)
    options = {
        'y':'send',
        'q':'abort',
        'a':'add attachment',
        'c':'add recipients',
        's':'edit subject',
        't':'edit recipient'}
    subheight = 5 + l + len(options) + 4
    w = min(90 + width % 2, width - 2)
    h = min(subheight + height % 2, height - 2)
    indent = (width - w)//2
    top = (height - h)//2
    confscr = curses.newwin(h,w,top,indent)
    confscr.border()

    confscr.attron(curses.color_pair(4))
    confscr.addstr(1,1,("You are about to send an email!")[:(w - 2)])
    confscr.addstr(2,1,("To: "+ state['to'])[:(w - 2)])
    confscr.addstr(3,1,("From: "+ myemail)[:(w - 2)])
    confscr.addstr(4,1,("Subject: " + state['subject'])[:(w - 2)])
    confscr.addstr(5,1,("Attachments: ")[:(w - 2)])

    # listAttachments(attachments)
    for i,a in enumerate(attachments):
      confscr.addstr(6+i, 3, ('- ' + a)[:(w - 4)]) 

    confscr.addstr(6 + l,1,("Options:")[:(w - 2)])

    for i,key in enumerate(options.keys()):
      confscr.addstr(7 + i + l, 3, ('- ' + key + ': ' + options[key])[:(w - 4)])

    confscr.attroff(curses.color_pair(4))
    confscr.refresh()
    stdscr.refresh()
    k = stdscr.getch()


def drawAttachments(stdscr, state, attachments):
  k = 0
  cursor_y = 0
  # Clear and refresh the screen for a blank canvas
  # Start colors in curses
  curses.curs_set(0)
  curses.start_color()
  curses.use_default_colors()
  for i in range(16):
    curses.init_pair(i, i, -1)
  for i in range(16, 32):
    curses.init_pair(i, i - 16, 3)
  for i in range(32, 48):
    curses.init_pair(i, i - 32, 15)
  stdscr.clear()
  stdscr.refresh()

  numOfAttachments = len(attachments)
  selectedAttachment = attachments[0]
  # Loop where k is the last character pressed
  while 1:
    height, width = stdscr.getmaxyx()

    if k == curses.KEY_RESIZE:
      height, width = stdscr.getmaxyx()
      stdscr.addstr(height - 1, 0, ' ' * (width - 1))

    elif k == curses.KEY_DOWN:
      cursor_y = cursor_y + 1

    elif k == curses.KEY_UP:
      cursor_y = cursor_y - 1
    
    elif k == ord('s'):
      # Try to save selectedAttachment.
      saveAttachment(mkService(), selectedAttachment)
      state['action'] = 'SAVED_ATTACHMENT'
      return state

    elif k == ord('q'):
      state['action'] = 'FINISHED_VIEWING_ATTACHMENTS'
      return state

    cursor_y = max(0, cursor_y)
    cursor_y = min(height-3, cursor_y, numOfAttachments - 1)
    # Update selected header.
    selectedAttachment = attachments[cursor_y]

    for i, a in enumerate(attachments[:height - 2]):
      display = a.display()
      l1 = len(display)
      stdscr.attron(curses.color_pair(4))
      if cursor_y == i:
        stdscr.attron(curses.color_pair(20))
        stdscr.attron(curses.A_BOLD)
        stdscr.addstr(i, 0, display)
        if (width - l1) > 0:
          stdscr.addstr(i, l1, " " * (width - l1))
        stdscr.attroff(curses.A_BOLD)
        stdscr.attroff(curses.color_pair(20))
      else:
        stdscr.addstr(i, 0, display)
        if (width - l1) > 0:
          stdscr.addstr(i, l1, " " * (width - l1))
      stdscr.attroff(curses.color_pair(4))
    for i in range(numOfAttachments, height - 2):
      stdscr.addstr(i,0,' ' * width)

    # Refresh the screen
    stdscr.refresh()

    # Wait for next input
    k = stdscr.getch()


def drawHeaders(stdscr, currentAccount, getHeadersFunc, **kwargs):
  k = 0
  state = kwargs.get('state', None)
  if state:
    cursor_y = state['cursor_y']
    position = state['position']
    if 'thread' in state:
      # (state['thread']).start()
      t = state.pop('thread',None)
      t.start()
  else:
    cursor_y = 0
    position = 0

  # Clear and refresh the screen for a blank canvas
  # Start colors in curses
  curses.curs_set(0)
  curses.start_color()
  curses.use_default_colors()
  for i in range(16):
    curses.init_pair(i, i, -1)
  for i in range(16, 32):
    curses.init_pair(i, i - 16, 3)
  for i in range(32, 48):
    curses.init_pair(i, i - 32, 15)

  excludedLabels = ['SPAM', 'TRASH']
  includedLabels = ['INBOX']
  searchTerms = None
  showLabels = False
  headers = getHeadersFunc(position, 45, excludedLabels, includedLabels,
      False)
  selectedHeader = headers[cursor_y]
  selectedHeaders = []
  numOfHeaders = getHeadersFunc(position,45,excludedLabels,includedLabels,True)

  stdscr.clear()
  stdscr.refresh()

  # Loop where k is the last character pressed
  while 1:

    height, width = stdscr.getmaxyx()

    if k == curses.KEY_RESIZE:
      height, width = stdscr.getmaxyx()
      stdscr.addstr(height - 1, 0, ' ' * (width - 1))

    elif k == ord(' '):
      # Select mail
      if selectedHeader not in selectedHeaders:
        selectedHeaders.append(selectedHeader)
        k = curses.KEY_DOWN 
      else:
        selectedHeaders.remove(selectedHeader)

    if k == curses.KEY_DOWN:
      cursor_y = cursor_y + 1
      if cursor_y == height - 2:
        position = min(position + 1, numOfHeaders - height + 2)
        # position = position + 1
        # Update list of messages.
        headers = getHeadersFunc(position, height, excludedLabels, 
            includedLabels,False)

    elif k == curses.KEY_UP:
      cursor_y = cursor_y - 1
      if cursor_y == -1:
        position = max(position - 1, 0)
        # Update list of messages.
        headers = getHeadersFunc(position, height, excludedLabels, 
            includedLabels,False)
        # position = position - 1

    elif k == curses.KEY_NPAGE:
      position = min(
          position + height - 7, max(numOfHeaders - height + 2, 0), numOfHeaders - 1)
      # position = position + height - 7
      # Update list of messages.
      headers = getHeadersFunc(position, height, excludedLabels, 
          includedLabels,False)

    elif k == curses.KEY_PPAGE:
      position = max(position - height + 7, 0)
      headers = getHeadersFunc(position, height, excludedLabels, 
          includedLabels,False)

    elif k == ord('\n'):
      message = readMessage(mkService(), selectedHeader.messageId)
      state = {'action': 'READ',
               'cursor_y': cursor_y,
               'position': position,
               'continue': True,
               'messageId': selectedHeader.messageId,
               'message': message}
      return state

    elif k == ord('r'):
      message = readMessage(mkService(), selectedHeader.messageId)
      state = {'action': 'REPLY',
               'cursor_y': cursor_y,
               'position': position,
               'header': selectedHeader,
               'continue': True,
               'message': message}
      return state

    elif k == ord('f'):
      to = getInput(stdscr, "Forward to: ", height, width)
      if to:
        message = readMessage(mkService(), selectedHeader.messageId)
        state = {'action': 'FORWARD',
                 'cursor_y': cursor_y,
                 'position': position,
                 'header': selectedHeader,
                 'continue': True,
                 'to': to,
                 'message': message}
        stdscr.addstr(height - 1, 0, ' ' * (width - 1))
        curses.curs_set(0)
        return state

    elif k == ord('m'):
      to = getInput(stdscr, "Send to: ", height, width)
      if to:
        subject = getInput(stdscr, "Subject: ", height, width)
        if subject:
          state = {'action': 'NEW',
                   'cursor_y': cursor_y,
                   'position': position,
                   'continue': True,
                   'to': to,
                   'subject': subject}
           
          stdscr.addstr(height - 1, 0, ' ' * (width - 1))
          curses.curs_set(0)
          with open(TMPDIR_WINDOW + 'stdscr.window','wb') as f:
            stdscr.putwin(f)
          return state
      curses.curs_set(0)

    elif k == ord('d'):
      k = stdscr.getch()
      if k == ord('d'):
        # Delete message (add 'TRASH' label and 
        # remove 'UNREAD' label if present).
        if len(selectedHeaders) == 0:
          selectedHeaders.append(selectedHeader)
        selectedIds = [h.messageId for h in selectedHeaders]
        state = {'action': 'DELETE',
                 'cursor_y': cursor_y,
                 'position': position,
                 'continue': True,
                 'messageIds': selectedIds}
        # Add 'TRASH' and remove 'UNREAD' labels. 
        logger.info('Modify local label DB: + "TRASH", - "UNREAD".')
        s = Session()
        addLabels(s, [(id, ['TRASH']) for id in selectedIds])
        removeLabels(s, [(id, ['UNREAD']) for id in selectedIds])
        s.commit()
        Session.remove()
        headers = getHeadersFunc(position, height, excludedLabels, 
            includedLabels,False)
        numOfHeaders = getHeadersFunc(position, height, excludedLabels, 
            includedLabels,True)
        return state

    elif k == ord('l'):
      k = stdscr.getch()
      if k == ord('l'):
        showLabels = not showLabels
      else:
        if k == ord('u'):
          excludedLabels = ['SPAM', 'TRASH']
          includedLabels = ['UNREAD']
        elif k == ord('i'):
          excludedLabels = ['SPAM', 'TRASH']
          includedLabels = ['INBOX']
        elif k == ord('s'):
          excludedLabels = []
          includedLabels = ['SENT']
        elif k == ord('t'):
          excludedLabels = ['SPAM']
          includedLabels = ['TRASH']
        position = 0
        headers = getHeadersFunc(position, height, excludedLabels, 
            includedLabels,False)
        numOfHeaders = getHeadersFunc(position, height, excludedLabels, 
            includedLabels,True)

    elif k == ord('/'):
      searchTerms = getInput(stdscr, "Enter search terms: ", height, width)
      if searchTerms:
        results = _search(searchTerms)
        getHeadersFunc = lambda a,b,c,d,e: __getHeaders(results,a,b,c,d,e)
        position = 0
        headers = getHeadersFunc(position, height, excludedLabels, 
            includedLabels,False)
        numOfHeaders = getHeadersFunc(position, height, excludedLabels, 
            includedLabels,True)
      curses.curs_set(0)

    elif k == ord('c'):
      # Clear search terms.
      if searchTerms:
        getHeadersFunc = (lambda a, b, c, d, e:
            __getHeaders(Session().query(MessageInfo), a, b, c, d, e))
        searchTerms = None
        position = 0
        headers = getHeadersFunc(position, height, excludedLabels, 
            includedLabels,False)
        numOfHeaders = getHeadersFunc(position, height, excludedLabels, 
            includedLabels,True)

    elif k == ord('v'):
      # View attachments.
      attachments = getAttachments(mkService(),selectedHeader)
      if attachments:
        state = {
            'action' : 'VIEW_ATTACHMENTS',
            'cursor_y': cursor_y,
            'position': position,
            'continue': True,
            'attachments': attachments
            }
        return state

    elif k == ord('q'):
      # Quit.
      state = {'continue': False}
      return state

    if numOfHeaders == 0:
      for i in range(height - 2):
        stdscr.addstr(i,0,' ' * width)
      noMessages = "No messages found! Press 'c' to go back."
      stdscr.addstr(height - 1, 0, noMessages)
      stdscr.addstr(height - 1, len(noMessages), " " *
                    (width - 1 - len(noMessages)))
    else:
      # Update line number.
      cursor_y = max(0, cursor_y)
      cursor_y = min(height-3, cursor_y, numOfHeaders - 1)
      # Update selected header.
      selectedHeader = headers[cursor_y]

      for i, h in enumerate(headers[:height - 2]):
        display = h.display(15, width)
        l1 = len(display)
        stdscr.attron(curses.color_pair(4))
        if cursor_y == i and h in selectedHeaders:
          stdscr.attron(curses.color_pair(21))
          stdscr.attron(curses.A_BOLD)
          stdscr.addstr(i, 0, display)
          if (width - l1) > 0:
            stdscr.addstr(i, l1, " " * (width - l1))
          stdscr.attroff(curses.A_BOLD)
          stdscr.attroff(curses.color_pair(21))
        elif cursor_y == i:
          stdscr.attron(curses.color_pair(20))
          stdscr.attron(curses.A_BOLD)
          stdscr.addstr(i, 0, display)
          if (width - l1) > 0:
            stdscr.addstr(i, l1, " " * (width - l1))
          stdscr.attroff(curses.A_BOLD)
          stdscr.attroff(curses.color_pair(20))
        elif h in selectedHeaders:
          stdscr.attron(curses.color_pair(5))
          stdscr.attron(curses.A_BOLD)
          stdscr.addstr(i, 0, display)
          if (width - l1) > 0:
            stdscr.addstr(i, l1, " " * (width - l1))
          stdscr.attroff(curses.A_BOLD)
          stdscr.attroff(curses.color_pair(5))
        else:
          stdscr.addstr(i, 0, display)
          if (width - l1) > 0:
            stdscr.addstr(i, l1, " " * (width - l1))
        stdscr.attroff(curses.color_pair(4))
      if numOfHeaders < height - 2:
        for i in range(numOfHeaders, height - 1):
          stdscr.addstr(i, 0, " " * width)

    # Render status bar
    StatusBarInfo(
        currentAccount,
        includedLabels,
        excludedLabels,
        selectedHeader,
        searchTerms,
        numOfHeaders,
        totalMessages,
        position + cursor_y + 1,
        showLabels).mkStatusBar(stdscr, height, width)

    if state:
      if 'action' in state:
        if state['action'] == 'SAVED_ATTACHMENT':
          putMessage(stdscr,height,width,"Attachment saved successfully.")
          state['action'] = ''
    # Refresh the screen
    stdscr.refresh()

    # Wait for next input
    k = stdscr.getch()
# <---


W3MARGS = ["w3m", "-T", "text/html", "-s", "-o", "display_image=False",
           "-o", "confirm_qq=False", "-o", "auto_image=False"]
TMPDIR_REPLIES = 'tmp/replies/'
TMPDIR_WINDOW = 'tmp/window/'
DLS = 'downloads/'
FZFARGS = ['fzf', '--height', '9']


def VIMARGS(messageId):
  return ["nvim", "-c", "set spell", "-c", "startinsert", "-c",
          "f " + TMPDIR_REPLIES + messageId]


def saveAttachment(service, attachment):
  messageId = attachment.messageId
  try:
    message = service.users().messages().get(userId='me',
        id=messageId).execute()

    for part in message['payload']['parts']:
      if part['filename']:
        if part['partId'] == attachment.partId:

          if 'data' in part['body']:
            data = base64.urlsafe_b64decode(part['body']['data']
                                                 .encode('utf-8'))
          else:
            attachmentId = part['body']['attachmentId']
            a = service.users().messages().attachments()\
                .get(userId='me', id=attachmentId,messageId=messageId)\
                .execute()
            data = base64.urlsafe_b64decode(a['data'].
                encode('utf-8'))

          path = ''.join([DLS, part['filename']])

          with open(path, 'wb') as f:
            f.write(data)

  except errors.HttpError as e:
    print('An error occurred: {}'.format(e))


def getAttachments(service, header):
  messageId = header.messageId
  attachments = []
  q = s.query(Attachments).filter(Attachments.messageId == messageId)
  if q.first():
    # Attachment info exists in db - use this.
    attachments = q.all()
  else:
    # Fetch attachment info.
    try:
      message = service.users().messages().get(userId='me', 
          id=messageId).execute()

      for part in message['payload']['parts']:
        if part['filename']:
          a = Attachments(
              messageId,
              part['partId'],
              part['filename'],
              part['mimeType'],
              part['body']['size'])
          s.add(a)
          attachments.append(a)

    except errors.HttpError as e:
      print('An error occurred: {}'.format(e))
  if len(attachments) == 0:
    # In the future this can probably happen automagically.
    logger.info('Attempting to remove false positive attachment signal')
    q = s.query(MessageInfo).filter(MessageInfo.messageId == messageId)\
        .update({MessageInfo.hasAttachments: False},
        synchronize_session='evaluate')
    s.commit()
    logger.info('Signal removed.')
  else: 
    return attachments

def mkReplyInfo(header, formatedMessage):
  lines = []
  for line in formatedMessage.stdout:
    if line == '\n':
      lines.append(line + '> ')
    else:
      lines.append(line)
  replyInfo = 'On {} <{}> wrote:'.format(
      header.timeForReply(),
      header.parseSender()[0]) 
  lines = ['\n\n', replyInfo, '\n\n>'] + lines
  return ''.join(lines)


def mkForwardInfo(header, formatedMessage):
  lines = []
  for line in formatedMessage.stdout:
    if line == '\n':
      lines.append(line + '> ')
    else:
      lines.append(line)
  sender = header.parseSender()
  forwardInfo = ' ----- Forwarded message from {} <{}> -----'.format(
      sender[1],
      sender[0])
  lines = ['\n\n', forwardInfo, '\n\n>'] + lines
  return ''.join(lines)


def postRead(service, messageId):
  # Mark message as read.
  # Remove 'UNREAD' label from local storage.
  logger.info('Removing label from local storage.')
  s = Session()
  removeLabels(s, [(messageId, ['UNREAD'])])
  s.commit()
  Session.remove()
  # Remove unread label from Google servers.
  logger.info('Removing label from Google servers.')
  body = {'removeLabelIds': ['UNREAD'], 'addLabelIds': []}
  try:
    service().users().messages().modify(userId='me', id=messageId,
                                        body=body).execute()
  except errors.HttpError as e:
    print(e)


def postSend(service, sender, draftId, **kwargs):
  '''
  Actually send the message. 
  Gets run in a thread while the mainloop restarts.

  Args:
    service: API service object.
    sender: Whoever is sending email.
    draftId: The id corresponding to the tmp file of the message text.

  Keyword args:
    type: One of NEW, REPLY, FORWARD.
    attachments: If present a list of files to attach.
    to: Who to send the mail to. Only needed if type is NEW or FORWARD.
    subject: Only if type is NEW.
    header: If type is reply or foreward, this must be present.

  Returns: None
  '''
  
  try:
    with open(TMPDIR_REPLIES + draftId, 'r') as f:
      message = createMessage(sender, f.read(), **kwargs) 
    # Send the message.
    message = sendMessage(service(), 'me', message)
    # Mark it as read if it wasn't already.
    if kwargs['type'] in ['REPLY', 'FORWARD']:
      header = kwargs['header']
      postRead(service, header.messageId)
    # Clean up.
    os.remove(TMPDIR_REPLIES + draftId)
    # Add message to local db.
    s = Session()
    addMessages(s, service(), [message['id']])
    s.commit()
    Session.remove()
    # make this message more useful!
    logger.info('Email sent successfully.')
  except Exception as e:
    # Something went wrong.
    logger.warning(e)

''' 
  Not needed anymore
def postCompose(service, myemail, to, subject, attachments, messageId):
  # Make the message
  try:
    logger.debug('Trying to send a message.')
    with open(TMPDIR_REPLIES + messageId, 'r') as f:
      if len(attachments) == 0:
        message = createNewMessage(myemail, to, subject, f.read())
      else:
        message = createNewMessageWithAttachment(myemail, to, subject, 
            f.read(), attachments)
    # Send the message.
    message = sendMessage(service(), myemail, message)
    # Clean up.
    logger.info('Removing temporary files.')
    os.remove(TMPDIR_REPLIES + messageId)
    # Add message to local db.
    logger.debug(str(message))
    s = Session()
    addMessages(s, service(), [message['id']])
    s.commit()
    Session.remove()
    logger.info('Email sent successfully.')
  except errors.Error as e:
    # File didn't exist.
    logger.warning(e)
'''


def postDelete(service, messageIds):
  # Remove unread label from Google servers.
  logger.info('Modify labels in remote DB: + "TRASH", - "UNREAD".')
  body = {'ids': messageIds,
      'removeLabelIds': ['UNREAD'],
      'addLabelIds': ['TRASH']}
  try:
    service().users().messages().batchModify(userId='me', body=body).execute()
  except errors.HttpError as e:
    print(e)


def chooseAttachment(directory):
  # Stole this from http:github.com/dahlia/iterfzf.
  # directory: This is the base directory for the fuzzy search.
  proc = None
  for line in listFiles(directory):
    if proc is None:
      proc = Popen(
          FZFARGS,
          stdin=PIPE,
          stdout=PIPE,
          stderr=None
      )
      stdin = proc.stdin
    line = line.encode('utf-8')
    try:
      stdin.write(line + b'\n')
      stdin.flush()
    except IOError as e:
      if e.errno != errno.EPIPE and errno.EPIPE != 32:
        raise
      break
  if proc is None or proc.wait() not in [0, 1]:
    return None
  try:
    stdin.close()
  except IOError as e:
    if e.errno != errno.EPIPE and errno.EPIPE != 32:
      raise
  stdout = proc.stdout
  decode = lambda t: t.decode('utf-8')
  output = [decode(ln.strip(b'\r\n\0')) for ln in iter(stdout.readline, b'')]
  try:
      return output[0]
  except IndexError:
      return None


def mainLoop(currentAccount):
  # Initialise the state.
  # Varaible to pass state between this loop and the inner loop.
  logger.info('Starting main loop...')
  state = None
  while True:

    # Run inner loop and update the state when it exits.
    state = curses.wrapper(
        lambda x: drawHeaders(
          x, currentAccount, lambda a,b,c,d,e: __getHeaders(
            s.query(MessageInfo),a,b,c,d,e
            ), state=state))
    # Process state.
    # Check we are not quitting.
    if state['continue'] == False:
      break

    # Read an email.
    elif state['action'] == 'READ':
      message = state['message']
      run(W3MARGS, input=message, encoding='utf-8')
      t = Thread(target=postRead,
                 args=(mkService, state['messageId']))
      state['thread'] = t
      # postRead(mkService(), state['messageId'])

    # Reply to an email.
    elif state['action'] == 'REPLY':
      header = state['header']
      message, draftId = state['message'], header.messageId
      # First format the message.
      formatedMessage = run(W3MARGS, input=message,
                            encoding='utf-8', stdout=PIPE)

      replyInfo = mkReplyInfo(header, formatedMessage)

      # Check that something didn't go wrong.
      if os.path.exists(TMPDIR_REPLIES + draftId):
        os.remove(TMPDIR_REPLIES + draftId)
      # Open the formated message in vim.
      run(VIMARGS(draftId), input=replyInfo,
          encoding='utf-8')
      myemail = currentAccount
      state['subject'] = mkSubject(header)
      state['to'] = header.sender
      state = curses.wrapper(lambda x: 
          drawConfirmationScreen(x, myemail, state))
      if state['action'] == 'SEND':
        attachments = state['attachments']
        t = Thread(target=postSend,
                   args=(mkService, myemail, draftId),
                   kwargs={'type': 'REPLY',
                           'attachments': attachments,
                           'header': header})
        state['thread'] = t
      elif state['action'] == 'DO_NOT_SEND':
        state.pop('thread', None)

    # Forward an email.
    elif state['action'] == 'FORWARD':
      header = state['header']
      message, draftId = state['message'], header.messageId
      # First format the message.
      formatedMessage = run(W3MARGS, input=message,
                            encoding='utf-8', stdout=PIPE)

      forwardInfo = mkForwardInfo(header, formatedMessage)

      # Check that something didn't go wrong.
      if os.path.exists(TMPDIR_REPLIES + draftId):
        os.remove(TMPDIR_REPLIES + draftId)
      # Open the formated message in vim.
      run(VIMARGS(draftId), input=forwardInfo,
          encoding='utf-8')
      myemail = currentAccount
      state['subject'] = mkSubject(header,isFwd=True)
      state = curses.wrapper(lambda x: 
          drawConfirmationScreen(x, myemail, state))
      if state['action'] == 'SEND':
        attachments = state['attachments']
        t = Thread(target=postSend,
                   args=(mkService, myemail, draftId),
                   kwargs = {'type': 'FORWARD',
                             'attachments': attachments,
                             'to': state['to'],
                             'header': header})
        state['thread'] = t
      elif state['action'] == 'DO_NOT_SEND':
        state.pop('thread', None)

    # Compose and send an email.
    elif state['action'] == 'NEW':
      to = state['to']
      subject = state['subject']
      # Open new message in vim.
      draftId = str(uuid4())
      if os.path.exists(TMPDIR_REPLIES + draftId):
        os.remove(TMPDIR_REPLIES + draftId)
      run(VIMARGS(draftId), encoding='utf-8')
      myemail = currentAccount
      state = curses.wrapper(lambda x: 
          drawConfirmationScreen(x, myemail, state))
      if state['action'] == 'SEND':
        attachments = state['attachments']
        t = Thread(target=postSend,
                   args=(mkService, myemail, draftId),
                   kwargs={'type': 'NEW',
                           'attachments': attachments,
                           'to': to,
                           'subject': subject})
        state['thread'] = t
      elif state['action'] == 'DO_NOT_SEND':
        state.pop('thread', None)

    # Move messages to Trash.
    elif state['action'] == 'DELETE':
      messageIds = state['messageIds']
      t = Thread(target=postDelete, name='DELETE',
                 args=(mkService, messageIds))
      state['thread'] = t

    # View Attachments.
    elif state['action'] == 'VIEW_ATTACHMENTS':
      attachments = state['attachments']
      state = curses.wrapper(lambda x: drawAttachments(x, state, attachments))


if __name__ == '__main__':
  setEscDelay()
  emailAddress = (s.query(UserInfo)[0]).emailAddress
  totalMessages = (s.query(UserInfo)[0]).totalMessages 
  mainLoop(emailAddress)

"""
vim:foldmethod=marker foldmarker=--->,<---
"""

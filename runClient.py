#!/usr/bin/python

# ---> Imports
from subprocess import run, PIPE
import re
import email
import curses
import base64
from uuid import uuid4
from collections import deque
# from textwrap import wrap
from common import (mkService, s, Labels, MessageInfo, Attachments,
        ListMessagesMatchingQuery, removeLabels, addLabels, Session, logger,
        UserInfo, addMessages)
from sendMail import createReply, createNewMessage, sendMessage
import os
from apiclient import errors
from threading import Thread
# <---

# ---> Helper functions
# ADDRESS_CHARS = re.compile('[!#$%&\'*+-/=?^_`{|}~"(),:;<>@[\]]|[A-Za-z]|[0-9]')


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
  return address


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
          re.sub('\n','',self.searchTerms),
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
'''

def _search(searchTerms):
  service = mkService()
  messageIds = [m['id'] for m in
          ListMessagesMatchingQuery(service,'me',query=searchTerms)]
  addMessages(s,service, messageIds)
  q = s.query(MessageInfo).filter(MessageInfo.messageId.in_(messageIds))
  s.commit()
  return q

def search(results,excludedLabels,includedLabels):
    return _getHeaders(results,excludedLabels,includedLabels) 

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
      (state['thread']).start()
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
  numOfHeaders = getHeadersFunc(position,45,excludedLabels,includedLabels,True)

  stdscr.clear()
  stdscr.refresh()

  # Loop where k is the last character pressed
  while 1:

    height, width = stdscr.getmaxyx()

    if k == curses.KEY_RESIZE:
      height, width = stdscr.getmaxyx()
      stdscr.addstr(height - 1, 0, ' ' * (width - 1))

    elif k == curses.KEY_DOWN:
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

    elif k == ord('m'):
      to = getInput(stdscr, "Send to: ", height, width)
      if to:
        subject = getInput(stdscr, "Subject: ", height, width)
        if subject:
          state = {'action': 'COMPOSE',
                   'cursor_y': cursor_y,
                   'position': position,
                   'continue': True,
                   'to': to,
                   'subject': subject}
          return state
      curses.curs_set(0)

    elif k == ord('d'):
      k = stdscr.getch()
      if k == ord('d'):
        # Delete message (move to trash).
        state = {'action': 'DELETE',
                 'cursor_y': cursor_y,
                 'position': position,
                 'continue': True,
                 'messageId': selectedHeader.messageId}
        # Add TRASH label to message
        logger.info('Adding label to local storage.')
        s = Session()
        addLabels(s, [(selectedHeader.messageId, ['TRASH'])])
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

    # Refresh the screen
    stdscr.refresh()

    # Wait for next input
    k = stdscr.getch()
# <---


W3MARGS = ["w3m", "-T", "text/html", "-s", "-o", "display_image=False",
           "-o", "confirm_qq=False", "-o", "auto_image=False"]
TMPDIR_REPLIES = 'tmp/replies/'


def VIMARGS(messageId):
  return ["nvim", "-c", "set spell", "-c", "startinsert", "-c",
          "f " + TMPDIR_REPLIES + messageId]


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
              part['filename'],
              part['mimeType'],
              part['body']['size'])
          s.add(a)
          attachments.append(a)

    except errors.HttpError as e:
      print('An error occurred: {}'.format(e))
  return attachments

def mkReplyInfo(header, formatedMessage):
  lines = []
  for line in formatedMessage.stdout:
    if line == '\n':
      lines.append(line + '>')
    else:
      lines.append(line)
  sender = header.parseSender()[0]
  replyInfo = "On " + header.timeForReply() + ' <' + sender + '> ' + 'wrote:'
  lines = ['\n\n', replyInfo, '\n\n>'] + lines
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


def postReply(service, myemail, header, messageId):
  # Make the message.
  try:
    with open(TMPDIR_REPLIES + messageId, 'r') as f:
      message = createReply(myemail, header, f.read())
    # Send the message.
    message = sendMessage(service(), 'me', message)
    # Mark it as read if it wasn't already.
    postRead(service, messageId)
    # Clean up.
    os.remove(TMPDIR_REPLIES + messageId)
    # Add message to local db.
    logger.debug(str(message))
    s = Session()
    addMessages(s, service(), [message['id']])
    s.commit()
    Session.remove()
    logger.info('Email sent successfully.')
  except Exception as e:
    # File didn't exist.
    logger.warning(e)


def postCompose(service, myemail, to, subject, messageId):
  # Make the message
  try:
    logger.debug('Trying to send a message.')
    with open(TMPDIR_REPLIES + messageId, 'r') as f:
      message = createNewMessage(myemail, to, subject, f.read())
    # Send the message.
    message = sendMessage(service(), 'me', message)
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


def postDelete(service, messageId):
  # Remove unread label from Google servers.
  logger.info('Adding label to Google servers.')
  body = {'removeLabelIds': [], 'addLabelIds': ['TRASH']}
  try:
    message = service().users().messages().modify(userId='me',
                                        id=messageId, body=body).execute()
  except errors.HttpError as e:
    print(e)

def updateHeaders():
    while 1:
        try:
            getHeadersFunc = headersFuncDeque.pop()
            logger.info('Getting headers')
            headers = getHeadersFunc()
            logger.info(headers[:6])
            headersDeque.append(headers)
        except:
            logger.info('For some reason the deque was empty...')
            pass
    
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
      message, messageId = state['message'], header.messageId
      # First format the message.
      formatedMessage = run(W3MARGS, input=message,
                            encoding='utf-8', stdout=PIPE)

      replyInfo = mkReplyInfo(header, formatedMessage)

      # Check that something didn't go wrong.
      if os.path.exists(TMPDIR_REPLIES + messageId):
        os.remove(TMPDIR_REPLIES + messageId)
      # Open the formated message in vim.
      run(VIMARGS(messageId), input=replyInfo,
          encoding='utf-8')
      myemail = currentAccount
      t = Thread(target=postReply,
                 args=(mkService, myemail, header, messageId))
      state['thread'] = t
      # postReply(mkService(),messageId)

    # Compose and send an email.
    elif state['action'] == 'COMPOSE':
      to = state['to']
      subject = state['subject']
      # Open new message in vim.
      messageId = str(uuid4())
      if os.path.exists(TMPDIR_REPLIES + messageId):
        os.remove(TMPDIR_REPLIES + messageId)
      run(VIMARGS(messageId), encoding='utf-8')
      myemail = currentAccount
      t = Thread(target=postCompose,
                 args=(mkService, myemail, to, subject, messageId))
      state['thread'] = t
      # postCompose(mkService(), messageId)

    # Move message to Trash.
    elif state['action'] == 'DELETE':
      messageId = state['messageId']
      t = Thread(target=postDelete, name='DELETE',
                 args=(mkService, messageId))
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

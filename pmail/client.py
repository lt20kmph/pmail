#!/usr/bin/python

# ---> Imports
import base64
import curses
import email
import errno
import os
import sys
import pickle
import re
import socket
# import logging

# from apiclient import errors
from pmail.common import (mkService, MessageInfo, Attachments,
                          listMessagesMatchingQuery, logger,
                          AddressBook, config)
# from itertools import cycle
from pmail.sendmail import (sendMessage, mkSubject, mkTo, createMessage)
from subprocess import run, PIPE, Popen
from threading import Thread, Event, Lock
from uuid import uuid4
from time import sleep
from queue import Queue
from shutil import which
# <---

# ---> State


class State():
  '''
  Class representing the state of the program.
  '''

  def __init__(self, **kwargs):
    # The line number of the cursor.
    self.cursor_y = kwargs.get('cursor_y', 0)
    # The scroll position.
    self.position = kwargs.get('position', 0)
    # The height of the window.
    self.height = kwargs.get('height', 0)
    # The next action to take.
    self.action = kwargs.get('action', None)
    # The selected account
    self.account = kwargs.get('account', None)
    # Any included labels.
    self.includedLabels = kwargs.get('includedLabels', ['INBOX'])
    # Any excluded labels.
    self.excludedLabels = kwargs.get('excludedLabels', ['SPAM', 'TRASH'])
    # Thread, which should be started in the background.
    self.thread = kwargs.get('thread', None)
    # Event, if not none, then we need to wait for this event.
    self.event = kwargs.get('event', None)
    # Any search terms in effect.
    self.searchTerms = kwargs.get('searchTerms', None)
    # A list of messageIds resulting from a search
    self.query = kwargs.get('query', None)
    # A list of selected messageIds.
    self.selectedMessages = kwargs.get('selectedMessages', [])
    # Visibility of labels.
    self.showLabels = kwargs.get('showLabels', False)
    # Global lock.
    self.globalLock = kwargs.get('lock', None)
    # Threading event, newMessagesArrived.
    self.newMessagesArrived = kwargs.get('newMessagesArrived', None)
    # Thread for handling keypress.
    self.keyHandler = kwargs.get('keyHandler', None)

  def read(self, messageId, message):
    '''
    Method to read mail.

    Args:
      messageId: The id of the message which will be read.
      message: The message which will be read.
    TODO: Why is messageId and message needed here?

    Returns:
      State()
    '''
    self.action = Read(messageId, message)
    return self

  def new(self, **kwargs):
    '''
    Method to compose new mail.

    Keyword Args:
      to: who to send the message to.
      subject: subject of the message.
    TODO: probably should not be keyword args...

    Returns:
      None
    '''
    sendTo = kwargs.get('to', None)
    subject = kwargs.get('subject', None)
    if sendTo:
      self.action = Send(type='NEW', sendTo=sendTo)
    if subject:
      try:
        self.action.addSubject(subject)
      except AttributeError:
        logger.warning('Trying to add subject to non-existent send action.')

  def reply(self, messageInfo, message):
    '''
    Method to reply to message.

    Args:
      messageInfo: MessageInfo() object which corresponding to the mail being
      replied to.
      message: The message being replied to.

    Returns:
      State()
    '''
    self.action = Send(messageInfo=messageInfo, message=message, type='REPLY')
    return self

  def replyToAll(self, messageInfo, message):
    '''
    Method to reply to all.

    Args:
      messageInfo: MessageInfo() object which corresponding to the mail being
      replied to.
      message: The message being replied to.

    Returns:
      State()
    '''
    self.action = Send(messageInfo=messageInfo,
                       message=message, type='REPLY_TO_ALL')
    return self

  def forward(self, messageInfo, message, to):
    '''
    Method to forward mail.

    Args:
      messageInfo: MessageInfo() object which corresponding to the mail being
      replied to.
      message: The message being replied to.
      to: Who to foreward the message to.

    Returns:
      State()
    '''
    # logger.info("Trying to forward a mail to {}".format(to))
    self.action = Send(messageInfo=messageInfo,
                       message=message, type='FORWARD', sendTo=to)
    return self

  def delete(self):
    '''
    Method to delete messages. (mark as read and add label trash.)
    '''
    self.action = Modify(self.selectedMessages, type='DELETE')
    return self

  def markAsRead(self):
    '''
    Method to mark messages as read.
    '''
    self.action = Modify(self.selectedMessages, type='MARK_AS_READ')
    return self

  def trash(self):
    '''
    Method to trash messages. (move to trash but don't read.)
    '''
    self.action = Modify(self.selectedMessages, type='TRASH')
    return self

  def viewAttachments(self):
    '''
    Method to view attachements.
    '''
    attachments = getAttachments(
        mkService(self.selectedMessages[0].emailAddress),
        self.selectedMessages[0],
        self.globalLock)
    if attachments:
      self.action = ViewAttachments(attachments)
      return True
    else:
      return False

  def addQuery(self, searchTerms):
    '''
    Method to perform a search.
    Args:
      searchTerms: The string to search for.
    '''
    self.position = 0
    if searchTerms:
      self.query = search(self.account, searchTerms, self.globalLock)
      self.searchTerms = searchTerms
    else:
      self.query = None
      self.searchTerms = None
    return self

  def removeQuery(self):
    '''
    Method to cancel a search if it is in effect.
    '''
    self.position = 0
    self.query = None
    self.searchTerms = None
    return self

  def switchAccount(self, account):
    '''
    Method to switch account.
    '''
    self.account = account
    self.position = 0
    self.removeQuery()
    return self

  def quit(self):
    '''
    Method to quit.
    '''
    self.action = Quit()
    return self

  def act(self):
    '''
    Method to perform an action if one is waiting.
    '''
    if self.action:
      # Perform action
      self.action.perform(state=self)
    else:
      logger.warning('Tried to act, but there is no action in the queue.')

# ---> mkStausBar
  def mkStatusBar(self, stdscr, height, width, numOfMessages,
                  selectedMessage, labelMap):
    '''
    Draw the status bar on the screen.

    Args:
      stdscr: The curses window object.
      height: Height of stdscr.
      width: Width of stdscr.
      numOfMessages: Number of messages in the current message list.
      selectedMessage: The index of the selectedMessage.

    Returns: None
    '''
    # user = ' \uf007 '
    # seperator = '\uf054'
    user = ' {} '.format(chr(config.user))
    seperator = chr(config.seperator)
    lUser = len(user)

    account = ' {} {} {} '.format(
        seperator,
        self.account if self.account else selectedMessage.emailAddress,
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

    numOfMessagesString = ' {} [{}/{} messages]'.format(
        seperator,
        self.position + self.cursor_y + 1,
        numOfMessages)
    n = len(numOfMessagesString)

    if self.showLabels is True:
      labels = str(selectedMessage.showLabels(labelMap))
    else:
      labels = ''
    labels = labels[: width - mbLen - acLen - stLen - n - 1]
    labelsLen = len(labels)

    whitespace = ' {}'.format(
        ' ' * (width - mbLen - acLen - stLen - n - 1))

    stdscr.attron(curses.color_pair(5))
    stdscr.attron(curses.A_BOLD)
    stdscr.addstr(height - 2, 0, user)
    stdscr.attroff(curses.A_BOLD)

    stdscr.addstr(height - 2, lUser, account)

    stdscr.addstr(height - 2, acLen, st)

    stdscr.attron(curses.A_BOLD)
    stdscr.addstr(height - 2, acLen + stLen, mb)
    stdscr.attroff(curses.A_BOLD)

    stdscr.addstr(height - 2, acLen + stLen + mbLen, numOfMessagesString)

    stdscr.addstr(height - 2, acLen + stLen + mbLen + n, labels)

    stdscr.addstr(height - 2, acLen + stLen +
                  mbLen + n + labelsLen, whitespace)
    stdscr.attroff(curses.color_pair(5))

    if numOfMessages > 0:
      snippet = ' On {} <{}> wrote: {} {}'.format(
          selectedMessage.timeForReply(),
          selectedMessage.parseSender()[0],
          selectedMessage.snippet,
          ' ' * width)
      # stdscr.addstr(height - 1, 0, snippet[:width - 1])
      try:
        stdscr.addstr(height - 1, 0, snippet[:width - 1])
      except curses.error:
        stdscr.addstr(height - 1, 0, ' ' * (width - 1))

# <---

# <---

# ---> Actions


ACTIONS = {
    'READ_A_MAIL',
    'MARK_AS_READ',
    'REMOVE_LABELS',
    'ADD_LABELS',
    'SEND_A_MAIL',
    'FORWARD',
    'REPLY',
    'REPLY_TO_ALL',
    'DELETE',
    'DO_NOT_SEND',
}


class Action():
  '''
  Class representing actions.
  Other actions inherit anything here, but so far there is nothing here.
  '''

  def __init__(self, action):
    self.action = action


class Read(Action):
  '''
  Class to read an email.
  '''

  def __init__(self, messageId, message):
    self.messageId = messageId
    self.message = message
    Action.__init__(self, 'READ')

  def perform(self, state):
    message = self.message
    run(config.w3mArgs(), input=message, encoding='utf-8')
    state.event = Event()
    state.thread = Thread(target=postRead,
                          name="postRead",
                          args=(mkService, state))
    return state


class Modify(Action):
  '''
  Class to modify an message.
  Can add or remove labels.
  '''

  def __init__(self, selectedMessages, type):
    self.selectedMessages = selectedMessages
    self.type = type
    Action.__init__(self, 'MODIFY')

  def perform(self, state):

    ms = self.selectedMessages
    lock = state.globalLock

    if self.type == 'DELETE':
      logger.info('Modify local label DB: + "TRASH", - "UNREAD".')
      data = {'action': 'ADD_LABELS',
              'labels': [(m.messageId, ['TRASH']) for m in ms]}
      sendToServer(data, lock)
      data = {'action': 'REMOVE_LABELS',
              'labels': [(m.messageId, ['UNREAD']) for m in ms]}
      sendToServer(data, lock)

    elif self.type == 'MARK_AS_READ':
      # Remove 'UNREAD' labels.
      logger.info('Modify local label DB: - "UNREAD".')
      data = {'action': 'REMOVE_LABELS',
              'labels': [(m.messageId, ['UNREAD']) for m in ms]}
      sendToServer(data, lock)

    elif self.type == 'TRASH':
      # Remove 'UNREAD' labels.
      logger.info('Modify local label DB: + "TRASH".')
      data = {'action': 'ADD_LABELS',
              'labels': [(m.messageId, ['TRASH']) for m in ms]}
      sendToServer(data, lock)

    t = Thread(target=postDelete, name='DELETE',
               args=(state, mkService, ms))  # [m.messageId for m in ms]))
    t.start()


class Send(Action):
  '''
  Class to send an email.
  '''

  def __init__(self, **kwargs):
    self.messageInfo = kwargs.get('messageInfo', None)
    self.message = kwargs.get('message', None)
    self.sendTo = kwargs.get('sendTo', None)
    self.type = kwargs.get('type', None)
    Action.__init__(self, 'SEND')

  def addSubject(self, subject):
    self.subject = subject

  def confirm(self, account):
    curses.wrapper(lambda x: drawConfirmationScreen(x, account, self))

  def perform(self, state):
    if self.type == 'NEW':
      draftId = str(uuid4())
      messageInfo = None
      # account = chooseAccount()
      account = state.account if state.account else state.unifiedAccount
      input = None

    elif self.type in ['REPLY', 'FORWARD', 'REPLY_TO_ALL']:
      messageInfo = self.messageInfo
      account = state.account if state.account else messageInfo.emailAddress
      message, draftId = self.message, messageInfo.messageId

      self.subject = mkSubject(messageInfo, self.type)

      if self.type in ['REPLY', 'REPLY_TO_ALL']:
        self.sendTo = mkTo(account, messageInfo, self.type)
      # elif self.type in ['FORWARD']:
        # logger.info('self.sendTo = {}'.format(self.sendTo))

      # First format the message.
      formatedMessage = run(config.w3mArgs(), input=message,
                            encoding='utf-8', stdout=PIPE)

      # Rewrite mkReplyInfo/mkForwardInfo...
      input = addInfo(messageInfo, formatedMessage, self.type)

    # Check that tmp file doesn't exist and remove if it does.
    if os.path.exists(os.path.join(config.tmpDir, draftId)):
      os.remove(os.path.join(config.tmpDir, draftId))

    # Open the formated message in vim.
    run(config.vimArgs(draftId), input=input, encoding='utf-8')

    # Check that tmp file exists ready to be sent.
    if os.path.exists(os.path.join(config.tmpDir, draftId)):
      type = self.type if self.type in ['NEW', 'FORWARD'] else 'REPLY'

      # Run confirmation loop.
      self.confirm(account)

      # Make the thread.
      if self.send == 'SEND':
        finishedUpdatingLocalDb = Event()
        t = Thread(target=postSend, name="postSend",
                   args=(mkService, finishedUpdatingLocalDb,
                         account, draftId),
                   kwargs={'type': type,
                           'attachments': self.attachments,
                           'to': self.sendTo,
                           'cc': self.cc,
                           'bcc': self.bcc,
                           'subject': self.subject,
                           'globalLock': state.globalLock,
                           'messageInfo': messageInfo})
        state.thread = t
        state.event = finishedUpdatingLocalDb
      elif self.send == 'DO_NOT_SEND':
        state.thread = None
    else:
      state.thread = None
    return state


class ViewAttachments(Action):
  '''
  Class to view attachements.
  '''

  def __init__(self, attachments):
    self.attachments = attachments
    Action.__init__(self, 'VIEW_ATTACHMENTS')

  def perform(self, state):
    # do something here and return something depending on if succesful or not
    curses.wrapper(lambda x: drawAttachments(
        x, state.account, state, self.attachments))


class Quit(Action):
  '''
  Class to quit.
  '''

  def __init__(self):
    # This is the only place where the underlying Action class is used.
    Action.__init__(self, 'QUIT')

  def perform(self):
    pass

# <---

# ---> Curses functions


def initColors():
  '''
  Initialise curses colors.
  '''
  curses.start_color()
  curses.use_default_colors()
  # Color pair for main list.
  curses.init_pair(1, config.fg, config.bg)

  # Color pair for selected messages.
  curses.init_pair(2, config.selFg, config.selBg)

  # Color pair for hightlighted messages.
  curses.init_pair(3, config.hiFg, config.hiBg)

  # Color pair for hightlighted and selected messages.
  curses.init_pair(4, config.selFg, config.hiBg)

  # Color pair for status bar.
  curses.init_pair(5, config.stFg, config.stBg)

# ---> Getting input and displaying messages


def getInput(stdscr, prompt, height, width):
  '''
  Get input from the user.

  Args:
    stdscr: The curses window object.
    prompt: Prompt to show the user.
    height: Height of stdscr.
    width: Width of stdscr.

  Returns:
    A string of charecters input by the user, or none of the user aborts
    by pressing ESCAPE.
  '''
  address = ""
  k, p = 0, len(prompt)
  stdscr.addstr(height - 1, 0, ' ' * (width - 1))
  stdscr.refresh()
  curses.curs_set(1)
  while k != '\n':
    l = len(address)
    stdscr.addstr(height - 1, 0, prompt + address)
    stdscr.addstr(height - 1, l + p, ' ' * (width - 1 - l - p))
    stdscr.move(height - 1, p + l)
    stdscr.refresh()
    k = stdscr.getkey()
    if (k == 'KEY_BACKSPACE'):
      try:
        address = address[:l - 1]
      except IndexError:
        pass
    elif (len(k) == 1) and (k != '\t'):
      if ord(k) == 27:
        return None
      else:
        address += k
  return address[:-1]


def putMessage(stdscr, height, width, message):
  '''
  Display a message at the bottom of the screen.

  Args:
    stdscr: The curses window object.
    height: Height of stdscr.
    width: Width of stdscr.
    message: The message to display

  Returns: None.
  '''
  line = (":: " + message + ' ' * width)[:width - 1]
  stdscr.addstr(height - 1, 0, line)

# <---

# ---> Confirmation Screen


# def drawConfirmationScreen(stdscr, account, state):
def drawConfirmationScreen(stdscr, account, sendAction):
  '''
  Loop to draw the confirmation screen that appears before email
  is finally sent.

  Args:
    stdscr: The curses window object.
    account: Currently selected account.
    sendAction: The Send() object which we are confirming.

  Returns:
    state: The state of the program.
  '''
  k = 0
  curses.curs_set(0)

  attachments = []
  cc = ''
  bcc = ''
  stdscr.clear()
  stdscr.refresh()

  while 1:
    height, width = stdscr.getmaxyx()

    l = len(attachments)
    options = {
        'y': 'send',
        'q': 'abort',
        'a': 'add attachment',
        'c': 'add recipients',
        's': 'edit subject',
        't': 'edit recipient'}
    c = 1  # counter for number of lines of infomation appearing.

    if k == curses.KEY_RESIZE:
      height, width = stdscr.getmaxyx()
      stdscr.refresh()

    elif k == ord('q'):
      # Don't send.
      sendAction.send = 'DO_NOT_SEND'
      return sendAction

    elif k == ord('y'):
      # Send.
      sendAction.send = 'SEND'
      sendAction.attachments = attachments if l > 0 else None
      sendAction.cc = cc if len(cc) > 0 else None
      sendAction.bcc = bcc if len(bcc) > 0 else None
      return sendAction

    elif k == ord('a'):
      # Add attachments.
      a = chooseAttachment(os.environ.get('HOME'))
      if a:
        attachments.append(a)
      stdscr.clear()
      stdscr.refresh()
      k = 0
      continue

    elif k == ord('c'):
      # Add recipients.
      # Either To, Bcc, or Cc
      # redraw options menu
      options = {
          't': 'To',
          'c': 'Cc',
          'b': 'Bcc'}
      stdscr.attron(curses.color_pair(1))
      for i in range(c + l + 1, height - 2):
        stdscr.addstr(i, 0, ' ' * width)
      for i, key in enumerate(options.keys()):
        stdscr.addstr(c + i + l + 1, 3, '- {}: {}'.format(key,
                                                          options[key])[:width - 2])
      stdscr.attroff(curses.color_pair(1))
      k = stdscr.getch()
      to = chooseAddress(account)
      if to:
        if k == ord('t'):
          sendAction.sendTo += (', ' + to)
        elif k == ord('c'):
          lcc = len(cc)
          cc += (', ' + to) if lcc > 0 else to
        elif k == ord('b'):
          lbcc = len(bcc)
          bcc += (', ' + to) if lbcc > 0 else to
      stdscr.clear()
      stdscr.refresh()
      k = 0
      continue

    elif k == ord('s'):
      # Edit subject.
      subject = getInput(stdscr, 'Enter new subject: ', height, width)
      stdscr.addstr(height - 1, 0, ' ' * (width - 1))
      curses.curs_set(0)
      sendAction.subject = subject
      k = 0
      continue

    elif k == ord('t'):
      # Edit recipient.
      to = chooseAddress(account)
      if to:
        sendAction.sendTo = to
      stdscr.clear()
      stdscr.refresh()
      k = 0
      continue

    stdscr.attron(curses.color_pair(1))
    stdscr.attron(curses.A_BOLD)
    stdscr.addstr(c, 1, ("You are about to send an email." +
                         " Please verify the details and press 'y' to send.")[:width - 2])
    stdscr.attroff(curses.A_BOLD)
    c += 1
    stdscr.addstr(c, 0, ' ' * (width))
    c += 1
    # Handle case when there are many to's..
    stdscr.addstr(c, 1, ("To: " + sendAction.sendTo)[:width - 2])
    c += 1
    if cc != '':
      stdscr.addstr(c, 1, ("Cc: " + cc)[:width - 2])
      c += 1
    if bcc != '':
      stdscr.addstr(c, 1, ("Bcc: " + bcc)[:width - 2])
      c += 1
    stdscr.addstr(c, 1, ("From: " + account)[:width - 2])
    c += 1
    stdscr.addstr(
        c, 1, ("Subject: " + sendAction.subject + ' ' * width)[:width - 2])
    c += 1
    stdscr.addstr(c, 1, ("Attachments: ")[:width - 2])
    c += 1

    # listAttachments(attachments)
    for i, a in enumerate(attachments):
      stdscr.addstr(c + i, 3, ('- ' + a)[:width - 4])

    stdscr.addstr(c + l, 1, ("Options:")[:width - 2])

    for i, key in enumerate(options.keys()):
      stdscr.addstr(c + i + l + 1, 3, '- {}: {}'.format(key,
                                                        options[key])[:width - 4])

    stdscr.attroff(curses.color_pair(1))
    stdscr.refresh()
    k = stdscr.getch()

# <---

# ---> Attachments


def drawAttachments(stdscr, account, state, attachments):
  '''
  Draw a list of attachments.
  Currently not handeling the case when len(attachments) > height.

  Args:
    stdscr: The curses window object.
    account: The currently selected account.
    state: The state of the program.
    attachments: The list of attachments from the highlighted message.

  Returns:
    state: The state of the program.
  '''
  k = 0
  cursor_y = 0
  # Clear and refresh the screen for a blank canvas
  # Start colors in curses
  curses.curs_set(0)
  initColors()
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

    elif k in [curses.KEY_DOWN, ord('j')]:
      cursor_y = cursor_y + 1

    elif k in [curses.KEY_UP, ord('k')]:
      cursor_y = cursor_y - 1

    elif k == ord('s'):
      # Try to save selectedAttachment.
      saveAttachment(mkService(account), selectedAttachment)
      state.action.saved = 'SAVED_ATTACHMENT'
      return state

    elif k == ord('q'):
      state.action.saved = 'NOT_SAVED'
      return state

    cursor_y = max(0, cursor_y)
    cursor_y = min(height - 3, cursor_y, numOfAttachments - 1)
    # Update selected header.
    selectedAttachment = attachments[cursor_y]

    for i, a in enumerate(attachments[:height - 2]):
      display = a.display()
      l1 = len(display)
      stdscr.attron(curses.color_pair(1))
      if cursor_y == i:
        stdscr.attron(curses.color_pair(3))
        stdscr.attron(curses.A_BOLD)
        stdscr.addstr(i, 0, display)
        if (width - l1) > 0:
          stdscr.addstr(i, l1, " " * (width - l1))
        stdscr.attroff(curses.A_BOLD)
        stdscr.attroff(curses.color_pair(3))
      else:
        stdscr.addstr(i, 0, display)
        if (width - l1) > 0:
          stdscr.addstr(i, l1, " " * (width - l1))
      stdscr.attroff(curses.color_pair(1))
    for i in range(numOfAttachments, height - 2):
      stdscr.addstr(i, 0, ' ' * width)

    # Refresh the screen
    stdscr.refresh()

    # Wait for next input
    k = stdscr.getch()

# <---

# ---> Draw message list


def drawMessages(stdscr, state, accountSwitcher, eventQue, labelMap):
  '''
  Loop to draw main screen of the program. A list of messages, which
  depends on the programs state.

  Args:
    stdscr: The curses window object.
    state: The state of the program.
    accountSwitcher: n-cycle to cycle through accounts where n is the number
    of accounts.
    eventQue: A Queue which will contain events when new messages show up.

  Returns:
    State()
  '''
  # Start colors in curses
  curses.curs_set(0)
  initColors()

  # Check if there are threads that need starting and
  # wait for them to complete certain tasks if necessary.
  if state.thread:
    state.thread.start()
    logger.info('Starting thread: {}.'.format(state.thread.name))
    state.thread = None
    if state.event:
      logger.info('Waiting for thread to do something.')
      state.event.wait()
    logger.info('Thread completed.')

  # Clear and refresh the screen for a blank canvas
  stdscr.clear()
  stdscr.refresh()
  height, width = stdscr.getmaxyx()
  state.height = height

  # Update the list of messages.
  messages = getMessages(state, returnCount=False)
  # if state.thread:
  #   if state.thread.name == "postRead":
  #     logger.info('Getting new message list.')
  numOfMessages = getMessages(state, returnCount=True)
  try:
    selectedMessage = messages[state.cursor_y]
  except IndexError:
    selectedMessage = messages[state.cursor_y - 1]
  except Exception:
    logger.exception('Caught error trying to select a message.')
  # logger.info('Labels: {}'.format([l.label for l in messages[0].labels]))

  # Loop where k is the last character pressed
  k = 0
  while 1:

    height, width = stdscr.getmaxyx()
    state.height = height
    logger.info('Keypress: k = {}'.format(k))
    # logger.info('eventQue size: {}'.format(eventQue.qsize()))

    if k == curses.KEY_RESIZE:
      height, width = stdscr.getmaxyx()
      state.height = height
      stdscr.addstr(height - 1, 0, ' ' * (width - 1))

    elif k == ord(' '):
      # Select mail
      if selectedMessage not in state.selectedMessages:
        state.selectedMessages.append(messages[state.cursor_y])
      else:
        state.selectedMessages.remove(messages[state.cursor_y])
      k = curses.KEY_DOWN
      continue

    elif k in [curses.KEY_DOWN, ord('j')]:
      state.cursor_y = state.cursor_y + 1
      if state.cursor_y == height - 2:
        state.position = min(state.position + 1, numOfMessages - height + 2)
        messages = getMessages(state, returnCount=False)

    elif k in [curses.KEY_UP, ord('k')]:
      state.cursor_y = state.cursor_y - 1
      if state.cursor_y == -1:
        state.position = max(state.position - 1, 0)
        messages = getMessages(state, returnCount=False)

    elif k in [curses.KEY_NPAGE, 4]:
      state.position = min(
          state.position + height - 7, max(numOfMessages - height + 2, 0), numOfMessages - 1)
      messages = getMessages(state, returnCount=False)

    elif k in [curses.KEY_PPAGE, 21]:
      state.position = max(state.position - height + 7, 0)
      messages = getMessages(state, returnCount=False)

    elif k == ord('M'):
      state.cursor_y = (height - 2) // 2

    elif k == ord('H'):
      state.cursor_y = 0

    elif k == ord('L'):
      state.cursor_y = height - 2

    elif k == ord('\n'):
      # Read a message.
      account = state.account if state.account else\
          selectedMessage.emailAddress
      message = readMessage(mkService(account),
                            selectedMessage.messageId)
      state.selectedMessages = [selectedMessage]
      state.read(selectedMessage.messageId, message)
      return state

    elif k == ord('r'):
      # Reply to message.
      account = state.account if state.account else\
          selectedMessage.emailAddress
      message = readMessage(mkService(account),
                            selectedMessage.messageId)
      state.reply(selectedMessage, message)
      stdscr.addstr(height - 1, 0, ' ' * (width - 1))
      curses.curs_set(0)
      return state

    elif k == ord('f'):
      # Forward message.
      account = state.account if state.account else\
          selectedMessage.emailAddress
      to = chooseAddress(account)
      if to:
        message = readMessage(mkService(account),
                              selectedMessage.messageId)
        state.forward(selectedMessage, message, to)
        stdscr.addstr(height - 1, 0, ' ' * (width - 1))
        curses.curs_set(0)
        return state

    elif k == ord('a'):
      # Reply to group/all.
      account = state.account if state.account else\
          selectedMessage.emailAddress
      message = readMessage(mkService(account),
                            selectedMessage.messageId)
      state.replyToAll(selectedMessage, message)
      stdscr.addstr(height - 1, 0, ' ' * (width - 1))
      curses.curs_set(0)
      return state

    elif k == ord('m'):
      # Make a new message.
      account = state.account if state.account else chooseAccount()
      state.unifiedAccount = account
      to = chooseAddress(account)
      stdscr.clear()
      stdscr.refresh()
      if to:
        # This is a hack to force screen to be redrawn before prompting
        # for a subject.
        state.new(to=to)
        # state = {'to': to}
        k = 'm0'
        continue

    elif k == ord('g'):
      k = stdscr.getch()
      if k == ord('g'):
        state.position = 0
        state.cursor_y = 0
        messages = getMessages(state, returnCount=False)

    elif k == ord('G'):
      state.cursor_y = height - 2
      state.position = numOfMessages - height + 2
      messages = getMessages(state, returnCount=False)

    elif k == ord('d'):
      # Delete message in varous ways.
      k = stdscr.getch()
      if len(state.selectedMessages) == 0:
        state.selectedMessages.append(selectedMessage)
      if k == ord('d'):
        # Delete message (add 'TRASH' label and
        # remove 'UNREAD' label if present).
        state.delete().act()

      elif k == ord('r'):
        # Mark as read. Remove unread label but leave in INBOX.
        state.markAsRead().act()

      elif k == ord('t'):
        # Add to TRASH but don't read.
        state.trash().act()

      messages = getMessages(state, returnCount=False, afterAction={
          'action': state.action.type,
          'messageIds': [m.messageId for m in state.selectedMessages]
      })
      numOfMessages = getMessages(state, returnCount=True)
      state.selectedMessages = []

    elif k == ord('l'):
      # Various label related features.
      k = stdscr.getch()
      if k == ord('l'):
        # Show the labels on the highlighted message.
        state.showLabels = not state.showLabels
      else:
        if k == ord('u'):
          # Show unread messages.
          state.excludedLabels = ['SPAM', 'TRASH']
          state.includedLabels = ['UNREAD']
        elif k == ord('i'):
          # Show messages in the inbox (default)
          state.excludedLabels = ['SPAM', 'TRASH']
          state.includedLabels = ['INBOX']
        elif k == ord('s'):
          # Show sent messages.
          state.excludedLabels = ['TRASH']
          state.includedLabels = ['SENT']
        elif k == ord('t'):
          # Show the trash.
          state.excludedLabels = ['SPAM']
          state.includedLabels = ['TRASH']
        state.position = 0
        messages = getMessages(state, returnCount=False)
        numOfMessages = getMessages(state, returnCount=True)

    elif k == ord('/'):
      # Do a search.
      searchTerms = getInput(stdscr, "Enter search terms: ", height, width)
      if searchTerms:
        state.addQuery(searchTerms)
        messages = getMessages(state, returnCount=False)
        numOfMessages = getMessages(state, returnCount=True)
      curses.curs_set(0)

    elif k == ord('c'):
      # Clear search terms.
      if state.searchTerms:
        state.addQuery(None)
        messages = getMessages(state, returnCount=False)
        numOfMessages = getMessages(state, returnCount=True)
      curses.curs_set(0)

    elif k == ord('v'):
      # View attachments.
      # attachments = getAttachments(mkService(state.account), selectedHeader)
      state.selectedMessages = [selectedMessage]
      attachments = state.viewAttachments()
      messages = getMessages(state, returnCount=False)
      if attachments:
        state.selectedMessages = []
        return state
      else:
        putMessage(stdscr, height, width,
                   'There are no attachments for this message. '
                   'press any key to continue.')
        k = stdscr.getch()
        state.selectedMessages = []

    elif k == ord('\t'):
      # Toggle between accounts.
      state.switchAccount(accountSwitcher.next())
      messages = getMessages(state, returnCount=False)
      numOfMessages = getMessages(state, returnCount=True)

    elif k == ord('b'):
      # Switch between accounts by index.
      k = stdscr.getch()
      for i in range(1, 10):
        if k == ord(str(i)):
          account = accountSwitcher.switch(i - 1)
          if account:
            state.switchAccount(account)
            messages = getMessages(state, returnCount=False)
            numOfMessages = getMessages(state, returnCount=True)
      if k == ord('u'):
        # Unified mailbox
        state.switchAccount(None)
        messages = getMessages(state, returnCount=False)
        numOfMessages = getMessages(state, returnCount=True)

    elif k == ord('q'):
      # Quit.
      logger.info('Exiting normally.')
      state.quit()
      return state

    if numOfMessages == 0:
      for i in range(height - 2):
        stdscr.addstr(i, 0, ' ' * width)
      noMessages = "No messages found! Press 'c' to go back."
      stdscr.addstr(height - 1, 0, noMessages)
      stdscr.addstr(height - 1, len(noMessages), " " *
                    (width - 1 - len(noMessages)))
    else:
      # Update line number.
      state.cursor_y = max(0, state.cursor_y)
      state.cursor_y = min(height - 3, state.cursor_y, numOfMessages - 1)
      # Update selected message.
      try:
        selectedMessage = messages[state.cursor_y]
      except IndexError:
        selectedMessage = messages[state.cursor_y - 1]
      except Exception:
        logger.exception('Caught error trying to select a message.')
      # state.selectedMessage = selectedMessage

      for i, h in enumerate(messages[:height - 2]):
        display = h.display(15, width, labelMap)
        l1 = len(display)
        stdscr.attron(curses.color_pair(1))
        if state.cursor_y == i and h in state.selectedMessages:
          stdscr.attron(curses.color_pair(4))
          stdscr.attron(curses.A_BOLD)
          stdscr.addstr(i, 0, display)
          if (width - l1) > 0:
            stdscr.addstr(i, l1, " " * (width - l1))
          stdscr.attroff(curses.A_BOLD)
          stdscr.attroff(curses.color_pair(4))
        elif state.cursor_y == i:
          stdscr.attron(curses.color_pair(3))
          stdscr.attron(curses.A_BOLD)
          stdscr.addstr(i, 0, display)
          if (width - l1) > 0:
            stdscr.addstr(i, l1, " " * (width - l1))
          stdscr.attroff(curses.A_BOLD)
          stdscr.attroff(curses.color_pair(3))
        elif h in state.selectedMessages:
          stdscr.attron(curses.color_pair(2))
          stdscr.attron(curses.A_BOLD)
          stdscr.addstr(i, 0, display)
          if (width - l1) > 0:
            stdscr.addstr(i, l1, " " * (width - l1))
          stdscr.attroff(curses.A_BOLD)
          stdscr.attroff(curses.color_pair(2))
        else:
          stdscr.addstr(i, 0, display)
          if (width - l1) > 0:
            stdscr.addstr(i, l1, " " * (width - l1))
        stdscr.attroff(curses.color_pair(1))
      if numOfMessages < height - 2:
        for i in range(numOfMessages, height - 1):
          stdscr.addstr(i, 0, " " * width)

    state.mkStatusBar(stdscr, height, width, numOfMessages, selectedMessage,
                      labelMap)

    if (state.action and
        state.action.action == 'VIEW_ATTACHMENTS' and
            state.action.saved == 'SAVED_ATTACHMENT'):
      # if state['action'] == 'SAVED_ATTACHMENT':
      putMessage(stdscr, height, width, "Attachment saved successfully.")
      state.action = None
      state.selectedMessages = []

    if k == 'm0':
      # Follow up on composing a new message. Ask for the subject.
      subject = getInput(stdscr, "Subject: ", height, width)
      if subject:
        state.new(subject=subject)
        return state
      else:
        state.action = None
        # state.pop('action', None)
      stdscr.addstr(height - 1, 0, ' ' * (width - 1))
      curses.curs_set(0)
    # Refresh the screen
    stdscr.refresh()

    # stdscr.nodelay(True)
    def waitForKey(stdscr, eventQue):
      '''
      Helper to wait for keypresses and put them into the queue.
      '''
      k = stdscr.getch()
      eventQue.put({'event': 'KeyPress', 'value': k})

    if (not state.keyHandler) or (not state.keyHandler.is_alive()):
      state.keyHandler = Thread(target=waitForKey, args=(stdscr, eventQue),
                                daemon=True)
      state.keyHandler.start()

    e = eventQue.get()

    if e['event'] == 'KeyPress':
      k = e['value']
    elif e['event'] == 'NewMsg':
      logger.info('Redrawing message list')
      messages = getMessages(state, returnCount=False)
      k = None

# <---

# <---

# ---> Post and Preprocessing functions

# ---> Postprocessing


def postDelete(state, service, messages):
  '''
  Modify labels on remote db after deleting.

  Args:
    state: The state of the program.
    service: The google API sevice object.
    messages: List of messageInfo objects which were
    deleted.

  Returns:
    None
  '''
  # Remove unread label from Google servers.
  def _postDelete(action, account, service, messageIds):
    if len(messageIds) > 0:
      if action.type == 'DELETE':
        body = {'ids': messageIds,
                'removeLabelIds': ['UNREAD'],
                'addLabelIds': ['TRASH']}
      elif action.type == 'MARK_AS_READ':
        body = {'ids': messageIds,
                'removeLabelIds': ['UNREAD'],
                'addLabelIds': []}
      elif action.type == 'TRASH':
        body = {'ids': messageIds,
                'removeLabelIds': [],
                'addLabelIds': ['TRASH']}
      try:
        service(account).users().messages().batchModify(
            userId='me', body=body).execute()
      except Exception:
        logger.exception(
            'Something went wrong trying to delete from remote server.'
        )

  logger.info('Modify labels in remote DB: + "TRASH", - "UNREAD".')
  if state.account:
    account = state.account
    messageIds = [m.messageId for m in messages]
    _postDelete(state.action, account, service, messageIds)
  else:
    for account in config.listAccounts():
      messageIds = [m.messageId for m in messages if m.emailAddress == account]
      _postDelete(state.action, account, service, messageIds)


def postSend(service, event, account, draftId, **kwargs):
  '''
  Actually send the message.
  Gets run in a thread while the mainloop restarts.

  Args:
    service: API service object.
    event: threading.Event object - set it to true once local db has updated.
    sender: Whoever is sending email.
    draftId: The id corresponding to the tmp file of the message text.

  Keyword args:
    type: One of NEW, REPLY, FORWARD.
    attachments: If present a list of files to attach.
    to: Who to send the mail to.
    cc: Carbon copies sent here.
    bcc: Blind carbon copies.
    subject: Subject of the mail.
    messageInfo: If type is reply or foreward, this must be present.

  Returns: None
  '''

  try:
    with open(os.path.join(config.tmpDir, draftId), 'r') as f:
      message = createMessage(account, f.read(), **kwargs)
    # Send the message.
    message = sendMessage(service(account), account, message)
    logger.info('Sent a message.')
    # TODO: Mark it as read if it wasn't already.
    # if kwargs['type'] in ['REPLY', 'FORWARD']:
    # messageInfo = kwargs['messageInfo']
    # postRead(account, event, service, messageInfo.messageId)
    # Clean up.
    os.remove(os.path.join(config.tmpDir, draftId))
    # Add message to local db.
    data = {'action': 'ADD_MESSAGES',
            'account': account,
            'messageIds': [message['id']]}
    lock = kwargs.get('globalLock', None)
    sendToServer(data, lock)
    # logger.info('data sent to server')
    event.set()
    # make this message more useful!
    # logger.info('Email sent successfully.')
  except Exception:
    # Something went wrong.
    logger.exception('Caught an Error while trying to send mail.')


# def postRead(account, event, service, messageId, lock):
def postRead(service, state):
  '''
  Mark message as read after reading.

  Args:
    service: The google API service object.
    state: State() state of the program.

  Returns:
    None
  '''
  # Mark message as read.
  # Remove 'UNREAD' label from local storage.
  account = state.account if state.account else\
      state.selectedMessages[0].emailAddress
  messageId = state.selectedMessages[0].messageId
  lock = state.globalLock
  data = {'action': 'REMOVE_LABELS',
          'labels': [(messageId, ['UNREAD'])],
          'account': account,
          'query': state.query,
          'position': state.position,
          'height': state.height,
          'excludedLabels': state.excludedLabels,
          'includedLabels': state.includedLabels,
          'afterAction': 'MARK_AS_READ'}
  response = sendToServer(data, lock)
  logger.info('Response from server: {}'.format(response))
  # logger.info('Data successfully sent to server.')
  # Set event to true so that main thread can continue.
  state.event.set()
  state.selectedMessages = []
  # Remove unread label from Google servers.
  # logger.info('Removing label from Google servers.')
  body = {'removeLabelIds': ['UNREAD'], 'addLabelIds': []}
  try:
    service(account).users().messages().modify(userId='me', id=messageId,
                                               body=body).execute()
  except Exception:
    logger.exception('Caught an error while reading mail.')

# <---

# ---> Preprocessing


def readMessage(service, messageId):
  '''
  Retrive a message from the server ready for reading.

  Args:
    service: The google API service object.
    messageId: The id of the message to retrive.

  Returns:
    The message as a string ready for w3m.
  '''
  msg = service.users().messages().get(
      userId='me', id=messageId, format='raw').execute()
  msg = msg['raw']
  msg = base64.urlsafe_b64decode(msg).decode('utf-8')
  msg = email.message_from_string(msg, policy=email.policy.default)
  return msg.get_body(('html', 'plain',)).get_content()


def addInfo(header, formatedMessage, type):
  '''
  Add a line containing infomation, and indent
  replies and forwarded messages.

  Args:
    header: the MessageInfo object of the mail being
    replied to or forwarded.
    formatedMessage: The formatedMessage as output by w3m
    as stdout.
    type: One of 'REPLY', 'REPLY_TO_ALL', 'FORWARD'.
  Returns:
    A String consisting of the new message.
  '''
  lines = []
  for line in formatedMessage.stdout:
    if line == '\n':
      lines.append(line + '> ')
    else:
      lines.append(line)

  if type in ['REPLY', 'REPLY_TO_ALL']:
    info = 'On {} <{}> wrote:'.format(
        header.timeForReply(),
        header.parseSender()[0])
  elif type == 'FORWARD':
    sender = header.parseSender()
    info = ' ----- Forwarded message from {} <{}> -----'.format(
        sender[1],
        sender[0])

  lines = ['\n\n', info, '\n\n>'] + lines
  return ''.join(lines)

# <---

# ---> Processing Attachments


def saveAttachment(service, attachment):
  '''
  Save an attachement.

  Args:
    service: The google API service object.
    attachment: The attachment object to be saved.

  Returns:
    None
  '''
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
                .get(userId='me', id=attachmentId, messageId=messageId)\
                .execute()
            data = base64.urlsafe_b64decode(a['data'].
                                            encode('utf-8'))

          path = os.path.join(config.dlDir, part['filename'])

          with open(path, 'wb') as f:
            f.write(data)

  except Exception:
    logger.exception('An error occured while tring to save an attachment.')
    # logger.warning('An error occurred: {}'.format(e))


def getAttachments(service, header, lock):
  '''
  Get a list of attachements, if any, from the highlighted message.

  Args:
    service: The google API service.
    header: The MessageInfo object corresponding to the highlighted
    message.

  Returns:
    List of attachment objects or None if there are no attachments.
  '''
  messageId = header.messageId
  attachments = []
  data = {'action': 'GET_QUERY',
          'class': Attachments,
          'messageIds': [messageId]}
  q = sendToServer(data, lock)
  # q = s.query(Attachments).filter(Attachments.messageId == messageId)
  if len(q) > 0:
    # Attachment info exists in db - use this.
    attachments = q
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
          # s.add(a)
          data = {'action': 'ADD_ATTACHMENT',
                  'attachment': a}
          sendToServer(data, lock)
          attachments.append(a)

    except Exception:
      logger.exception('An error occurred while getting attachments.')
  if len(attachments) == 0:
    logger.info('Trying to view attachments but there are none')
  else:
    return attachments
# <---

# <---

# ---> Searching and filtering.


def search(account, searchTerms, lock):
  '''
  Do a search.

  Args:
    account: Currently selected account.
    searchTerms: What to search for.

  Returns:
    query consiting of MessageInfo objects.
  '''
  service = mkService(account)
  messageIds = [m['id'] for m in
                listMessagesMatchingQuery(service, 'me', query=searchTerms)]
  data = {'action': 'ADD_MESSAGES',
          'account': account,
          'messageIds': messageIds}
  sendToServer(data, lock)
  data = {'action': 'GET_QUERY',
          'class': MessageInfo,
          'messageIds': messageIds}
  return [q.messageId for q in sendToServer(data, lock)]


def listFiles(directory):
  '''
  List the files in directory as a
  generator.
  '''
  for root, _, files in os.walk(directory):
    for f in files:
      yield os.path.join(root, f)


def chooseAttachment(x): return fzf(
    'Choose an attachment: ', listFiles(x))


def chooseAddress(x): return fzf(
    'To: ', AddressBook.addressList(x))

'''
# Wrapper for fzf to dump and restore window state before and after.
def fzfWrapper (stdscr, prompt, iterable):
  stdscr.refresh()
  with open(TMPDIR_WINDOW + 'stdscr.window','wb') as f:
    stdscr.putwin(f)
  out = fzf(prompt,iterable)
  stdscr.clear()
  with open(TMPDIR_WINDOW + 'stdscr.window','rb') as f:
    stdscr = curses.getwin(f)
  stdscr.refresh()
  return out
'''

def chooseAccount(): return fzf(
  'Send from: ', list(config.listAccounts())
)


def fzf(prompt, iterable):
  '''
  Use fzf to fuzzy search an iterable.
  Stole this from http:github.com/dahlia/iterfzf.

  Args:
    prompt: Prompt to show the user.
    iterable: iterable to search.
  '''
  proc = None
  for line in iterable:
    line = re.sub('\n', '', line)
    line = re.sub('\r', '', line)
    if proc is None:
      proc = Popen(
          config.fzfArgs(prompt),
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
  def decode(t): return t.decode('utf-8')
  output = [decode(ln.strip(b'\r\n\0')) for ln in iter(stdout.readline, b'')]
  try:
    return output[-1]
  except IndexError:
    return None

# <---

# ---> Main


def sendToServer(data, lock):
  '''
  Function to send data to the server.

  Args:
    data: What ever we should send to the server.
    lock: threading.Lock().

  Returns:
    A response from the server (possibly None).

  '''
  with lock:
    host = socket.gethostname()
    port = config.port
    sock = socket.socket()
    bufferSize = 1024

    try:
      sock.connect((host, port))
      pickledData = pickle.dumps(data)
      sizeOfPickle = len(pickledData)
      numOfChunks = sizeOfPickle // bufferSize + 1
      sock.send(sizeOfPickle.to_bytes(4, 'big'))

      for i in range(numOfChunks):
        sock.send(pickledData[i * bufferSize: (i + 1) * bufferSize])

      sizeOfResponse = int.from_bytes(sock.recv(4), 'big')
      response = b''

      while len(response) < sizeOfResponse:
        response += sock.recv(bufferSize)

      unpickledResponse = pickle.loads(response)
      sock.close()
      return unpickledResponse

    except ConnectionError:
      raise

    except Exception:
      logger.warning('There was an error while trying to send to server.')
      raise


def setEscDelay():
  '''
  This is needed so that when pressing ESCAPE to exit from the getInput
  function there is no noticable delay.
  '''
  os.environ.setdefault('ESCDELAY', '25')


def getMessages(state, **kwargs):
  '''
  Function to get the list of messages. Essentially just a small preprocessing
  wrapper around sendToServer.

  Args:
    state: State(), the state of pmail.

  Returns:
    List of messages.
  '''
  returnCount = kwargs.get('returnCount', False)
  afterAction = kwargs.get('afterAction', None)
  data = {'action': 'GET_MESSAGES',
          'account': state.account,
          'query': state.query,
          'position': state.position,
          'height': state.height,
          'excludedLabels': state.excludedLabels,
          'includedLabels': state.includedLabels,
          'count': returnCount,
          'afterAction': afterAction}
  return sendToServer(data, state.globalLock)


def mainLoop(lock, accountSwitcher, eventQue):
  '''
  Main loop of the program. This loop processes the state
  based on its 'action' and launches various subloops.
  '''
  logger.info('Starting main loop...')
  # account = next(accountSwitcher)
  account = accountSwitcher.next()
  # Initialise the state.
  state = State(account=account,
                lock=lock)
  try:
    labelMap = sendToServer({'action': 'GET_LABEL_MAP'}, lock)
  except ConnectionError:
    print('Could not connect to server!\r\n')
    logger.warning('Could not connect to the server.')
    sys.exit()
  while True:
    try:
      # Run inner loop and update the state when it exits.
      state = curses.wrapper(
          lambda x: drawMessages(x, state, accountSwitcher, eventQue,
                                 labelMap))
      if type(state.action).__name__ == 'Quit':
        break
      else:
        state.act()
    except ConnectionError:
      print('Could not connect to server!')
      logger.warning('Could not connect to the server.')
      sys.exit()
    except Exception:
      logger.exception('Something bad happened.')
      sys.exit()


def checkForNewMessages(lock, eventQue):
  '''
  Function to ask the server if new messages have arrived.

  Args:
    lock: threading.Lock()
    eventQue: Queue() in which to put an event if new messages did arrive.

  Returns:
    None
  TODO: Make this listen to the server (implement this as a server?)
  '''
  data = {'action': 'CHECK_FOR_NEW_MESSAGES',
          }
  logger.info('Asking server if anything new showed up.')
  while 1:
    try:
      response = sendToServer(data, lock)
      if response == 'newMessagesArrived':
        logger.info('New message detected.')
        # newMessagesArrived.clear()
        eventQue.put({'event': 'NewMsg'})
      sleep(10)
    except ConnectionError:
      print('Could not connect to server!\r\n')
      logger.warning('Could not connect to the server.')
      sys.exit()


def checkPrograms():
  '''
  Before staring the client check that the editor, pager and picker programs
  are present and give a friendly warning if not.
  '''
  progs = {}
  progs['editor'] = config.editor.split()[0]
  progs['pager'] = config.pager.split()[0]
  progs['picker'] = config.picker.split()[0]

  msgs = {}
  msgs['editor'] = 'You will not be able to write emails.'
  msgs['pager'] = 'You will not be able to read emails.'
  msgs['picker'] = 'You will not be able to use the address book' +\
                   ' or the file chooser.'

  def askToContinue(prog, msg):
    '''
    Give a friendly warning, and ask if client should launch anyway.

    Args:
      prog: Which program was missing.
      msg: Message to display.
    '''

    def _askToContinue(stdscr):
      '''
      Helper function for curses.
      '''
      height, width = stdscr.getmaxyx()
      if height < 4:
        logger.warning('Terminal too small to continue!')
        sys.exit()
      else:
        lines = []
        lines.append(f'You do not seem to have {progs[prog]} installed and ' +
                     'available in your $PATH.')
        lines.append(msg)
        lines.append(f'You can try modifying the {prog} setting in ' +
                     f'config.yaml, or installing {progs[prog]}.')
        lines.append("Press 'y' to ignore this message and continue, and " +
                     "'q' to exit.")
        for i, l in enumerate(lines):
          stdscr.addstr(i, 0, l[:width - 1])
        k = 0
        while 1:
          if k == ord('y'):
            return 'y'
          elif k == ord('q'):
            return 'q'
          k = stdscr.getch()

    r = curses.wrapper(_askToContinue)
    if r == 'q':
      sys.exit()

  for k in progs:
    if not which(progs[k]):
      askToContinue(k, msgs[k])


class AccountSwitcher():
  def __init__(self, accounts):
    self.accounts = list(accounts)
    self.numAccounts = len(accounts)
    self.account = self.accounts[0]

  def next(self):
    i = self.accounts.index(self.account)
    i = (i + 1) % self.numAccounts
    self.account = self.accounts[i]
    return self.account

  def switch(self, accountIndex):
    if accountIndex < self.numAccounts:
      self.account = self.accounts[accountIndex]
      return self.account
    else:
      logger.info('Tried to switch to account {}. But it does not exist!'
                  .format(accountIndex))


def start():
  '''
  Start the client.
  '''
  checkPrograms()
  setEscDelay()
  # accountSwitcher = cycle(config.listAccounts())
  accountSwitcher = AccountSwitcher(config.listAccounts())
  logger.setLevel(config.logLevel)
  lock = Lock()
  eventQue = Queue()
  t1 = Thread(target=mainLoop, args=(lock, accountSwitcher, eventQue,))
  t2 = Thread(target=checkForNewMessages, args=(lock, eventQue,),
              daemon=True)
  t1.start()
  t2.start()

  # Clean up tmp files.
  for f in os.listdir(config.tmpDir):
    os.remove(os.path.join(config.tmpDir, f))
# <---


"""
vim:foldmethod=marker foldmarker=--->,<---
"""

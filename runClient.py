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
import logging

from apiclient import errors
from common import (mkService, Labels, MessageInfo, Attachments,
                    listMessagesMatchingQuery, logger,
                    UserInfo, AddressBook, config)
from itertools import cycle
from sendMail import (sendMessage, mkSubject, mkTo, createMessage)
from subprocess import run, PIPE, Popen
from threading import Thread, Event
from uuid import uuid4
# <---

# ---> Curses functions


def initColors():
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
        address = address[:l-1]
      except:
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

# ---> Statusbar class


class StatusBarInfo():
  '''
  Class to store various data needed to render the status bar and a 
  method to render it.

  Args:
    account: Currently selected account.
    includedLabels: Labels included in the filter in __getHeaders.
    excludedLabels: Labels excluded by the filter in __getHeaders.
    selectedHeader: The hightlighted message.
    searchTerms: The terms searched for, if any.
    numOfHeaders: The number of messages in the query returned by __getHeaders.
    totalMessages: The total num of messages in account. (not used atm)
    currentMessageIndex: The index of the highlighted message.
    showLabels: A list of labels attached to the highlighted message.
  '''

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
    '''
    Draw the status bar on the screen.

    Args:
      stdscr: The curses window object.
      height: Height of stdscr.
      width: Width of stdscr.

    Returns: None
    '''
    # user = ' \uf007 '
    # seperator = '\uf054'
    user = ' {} '.format(chr(config.user))
    seperator = chr(config.seperator)
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

    stdscr.attron(curses.color_pair(5))
    stdscr.attron(curses.A_BOLD)
    stdscr.addstr(height - 2, 0, user)
    stdscr.attroff(curses.A_BOLD)

    stdscr.addstr(height - 2, lUser, account)

    stdscr.addstr(height - 2, acLen, st)

    stdscr.attron(curses.A_BOLD)
    stdscr.addstr(height - 2, acLen + stLen, mb)
    stdscr.attroff(curses.A_BOLD)

    stdscr.addstr(height - 2, acLen + stLen + mbLen, numOfMessages)

    stdscr.addstr(height - 2, acLen + stLen + mbLen + n, labels)

    stdscr.addstr(height - 2, acLen + stLen +
                  mbLen + n + labelsLen, whitespace)
    stdscr.attroff(curses.color_pair(5))

    if self.numOfHeaders > 0:
      snippet = ' On {} <{}> wrote: {} {}'.format(
          self.selectedHeader.timeForReply(),
          self.selectedHeader.parseSender()[0],
          self.selectedHeader.snippet,
          ' ' * width
      )
      try:
        stdscr.addstr(height - 1, 0, snippet[:width - 1])
      except:
        stdscr.addstr(height - 1, 0, ' ' * (width - 1))

# <---


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

# ---> Confirmation Screen


def drawConfirmationScreen(stdscr, account, state):
  '''
  Loop to draw the confirmation screen that appears before email
  is finally sent.

  Args:
    stdscr: The curses window object.
    account: Currently selected account.
    state: The state of the program.

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
      state['action'] = 'DO_NOT_SEND'
      return state

    elif k == ord('y'):
      # Send.
      state['action'] = 'SEND'
      state['attachments'] = attachments if l > 0 else None
      state['cc'] = cc if len(cc) > 0 else None
      state['bcc'] = bcc if len(bcc) > 0 else None
      return state

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
          state['to'] += (', ' + to)
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
      state['subject'] = subject
      k = 0
      continue

    elif k == ord('t'):
      # Edit recipient.
      to = chooseAddress(account)
      if to:
        state['to'] = to
      stdscr.clear()
      stdscr.refresh()
      k = 0
      continue

    stdscr.attron(curses.color_pair(1))
    stdscr.attron(curses.A_BOLD)
    stdscr.addstr(c, 1, ("You are about to send an email." +
                         " Please verify the detials and press 'y' to send.")[:width - 2])
    stdscr.attroff(curses.A_BOLD)
    c += 1
    stdscr.addstr(c, 0, ' ' * (width))
    c += 1
    # Handle case when there are many to's..
    stdscr.addstr(c, 1, ("To: " + state['to'])[:width - 2])
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
        c, 1, ("Subject: " + state['subject'] + ' ' * width)[:width - 2])
    c += 1
    stdscr.addstr(c, 1, ("Attachments: ")[:width - 2])
    c += 1

    # listAttachments(attachments)
    for i, a in enumerate(attachments):
      stdscr.addstr(c+i, 3, ('- ' + a)[:width - 4])

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
  Currently not handerlin the case when len(attachments) > height.

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


def drawMessages(stdscr, getMessagesFunc, state):
  '''
  Loop to draw main screen of the program. A list of messages, which maybe
  updated by changing the filtering function getMessagesFunc.

  Args:
    stdscr: The curses window object.
    getMessagesFunc: A filtering fuction to apply to the messages db.
  '''
  k = 0
  if state:
    cursor_y = state.get('cursor_y', 0)
    position = state.get('position', 0)
    account = state['account']
    if 'thread' in state:
      t = state.pop('thread', None)
      t.start()
      logger.info('starting thread')
      if 'event' in state:
        e = state.pop('event',None)
        e.wait()

  # Start colors in curses
  curses.curs_set(0)
  initColors()

  excludedLabels = ['SPAM', 'TRASH']
  includedLabels = ['INBOX']
  searchTerms = state.get('searchTerms', None)
  getMessagesFunc = state.get('getMessagesFunc', getMessagesFunc)
  showLabels = False
  headers = getMessagesFunc(position, 45, excludedLabels, includedLabels,
                            False)
  selectedHeader = headers[cursor_y]
  selectedHeadersIds = []
  numOfHeaders = getMessagesFunc(
      position, 45, excludedLabels, includedLabels, True)

  # Clear and refresh the screen for a blank canvas
  stdscr.clear()
  stdscr.refresh()

  # Loop where k is the last character pressed
  while 1:

    height, width = stdscr.getmaxyx()
    # logger.info('k is {}'.format(k))

    if k == curses.KEY_RESIZE:
      height, width = stdscr.getmaxyx()
      stdscr.addstr(height - 1, 0, ' ' * (width - 1))

    elif k == ord(' '):
      # Select mail
      if selectedHeader.messageId not in selectedHeadersIds:
        selectedHeadersIds.append(selectedHeader.messageId)
      else:
        selectedHeadersIds.remove(selectedHeader.messageId)
      k = curses.KEY_DOWN
      continue

    elif k in [curses.KEY_DOWN, ord('j')]:
      cursor_y = cursor_y + 1
      if cursor_y == height - 2:
        position = min(position + 1, numOfHeaders - height + 2)
        headers = getMessagesFunc(position, height, excludedLabels,
                                  includedLabels, False)

    elif k in [curses.KEY_UP, ord('k')]:
      cursor_y = cursor_y - 1
      if cursor_y == -1:
        position = max(position - 1, 0)
        # Update list of messages.
        headers = getMessagesFunc(position, height, excludedLabels,
                                  includedLabels, False)

    elif k in [curses.KEY_NPAGE, 4]:
      position = min(
          position + height - 7, max(numOfHeaders - height + 2, 0), numOfHeaders - 1)
      # Update list of messages.
      headers = getMessagesFunc(position, height, excludedLabels,
                                includedLabels, False)

    elif k in [curses.KEY_PPAGE, 21]:
      position = max(position - height + 7, 0)
      headers = getMessagesFunc(position, height, excludedLabels,
                                includedLabels, False)

    elif k == ord('M'):
      cursor_y = (height - 2)//2

    elif k == ord('H'):
      cursor_y = 0

    elif k == ord('L'):
      cursor_y = height - 2

    elif k == ord('\n'):
      # Read a message.
      message = readMessage(mkService(account), selectedHeader.messageId)
      state = {'action': 'READ',
               'account': account,
               'cursor_y': cursor_y,
               'position': position,
               'continue': True,
               'messageId': selectedHeader.messageId,
               'message': message}
      return state

    elif k == ord('r'):
      # Reply to message.
      message = readMessage(mkService(account), selectedHeader.messageId)
      state = {'action': 'REPLY',
               'account': account,
               'cursor_y': cursor_y,
               'position': position,
               'header': selectedHeader,
               'continue': True,
               'message': message}
      stdscr.addstr(height - 1, 0, ' ' * (width - 1))
      curses.curs_set(0)
      return state

    elif k == ord('f'):
      # Forward message.
      to = chooseAddress(account)
      if to:
        message = readMessage(mkService(account), selectedHeader.messageId)
        state = {'action': 'FORWARD',
                 'account': account,
                 'cursor_y': cursor_y,
                 'position': position,
                 'header': selectedHeader,
                 'continue': True,
                 'to': to,
                 'message': message}
        stdscr.addstr(height - 1, 0, ' ' * (width - 1))
        curses.curs_set(0)
        return state

    elif k == ord('g'):
      k = stdscr.getch()
      if k == ord('g'):
        position = 0
        cursor_y = 0
        headers = getMessagesFunc(position, height, excludedLabels,
                                  includedLabels, False)

    elif k == ord('G'):
      cursor_y = height - 2
      position = numOfHeaders - height + 2
      headers = getMessagesFunc(position, height, excludedLabels,
                                  includedLabels, False)

    elif k == ord('a'):
      # Reply to group/all.
      message = readMessage(mkService(account), selectedHeader.messageId)
      state = {'action': 'REPLYTOALL',
               'account': account,
               'cursor_y': cursor_y,
               'position': position,
               'header': selectedHeader,
               'continue': True,
               'message': message}
      stdscr.addstr(height - 1, 0, ' ' * (width - 1))
      curses.curs_set(0)
      return state

    elif k == ord('m'):
      # Make a new message.
      to = chooseAddress(account)
      stdscr.clear()
      stdscr.refresh()
      if to:
        # This is a hack to force screen to be redrawn before prompting
        # for a subject.
        state = {'to': to}
        k = 'm0'
        continue

    elif k == ord('d'):
      # Delete message in varous ways.
      k = stdscr.getch()
      # s = Session()
      if len(selectedHeadersIds) == 0:
        selectedHeadersIds.append(selectedHeader.messageId)
      if k == ord('d'):
        # Delete message (add 'TRASH' label and
        # remove 'UNREAD' label if present).
        state = {'action': 'DELETE',
                 'account': account,
                 'cursor_y': cursor_y,
                 'position': position,
                 'continue': True,
                 'messageIds': selectedHeadersIds}
        # Add 'TRASH' and remove 'UNREAD' labels.
        logger.info('Modify local label DB: + "TRASH", - "UNREAD".')
        data = {'action': 'ADD_LABELS',
                'labels': [(id, ['TRASH']) for id in selectedHeadersIds]}
        sendToServer(data)
        data = {'action': 'REMOVE_LABELS',
                'labels': [(id, ['UNREAD']) for id in selectedHeadersIds]}
        sendToServer(data)
        # Labels.addLabels(s, [(id, ['TRASH']) for id in selectedHeadersIds])

      elif k == ord('r'):
        # Mark as read. Remove unread label but leave in INBOX.
        state = {'action': 'MARK_AS_READ',
                 'account': account,
                 'cursor_y': cursor_y,
                 'position': position,
                 'continue': True,
                 'messageIds': selectedHeadersIds}
        # Remove 'UNREAD' labels.
        logger.info('Modify local label DB: - "UNREAD".')
        data = {'action': 'REMOVE_LABELS',
                'labels': [(id, ['UNREAD']) for id in selectedHeadersIds]}
        sendToServer(data)
        # Labels.removeLabels(s, [(id, ['UNREAD']) for id in
        # selectedHeadersIds])

      elif k == ord('t'):
        # Add to TRASH but don't read.
        state = {'action': 'TRASH',
                 'account': account,
                 'cursor_y': cursor_y,
                 'position': position,
                 'continue': True,
                 'messageIds': selectedHeadersIds}
        # Remove 'UNREAD' labels.
        logger.info('Modify local label DB: + "TRASH".')
        # Labels.addLabels(s, [(id, ['TRASH']) for id in selectedHeadersIds])
        data = {'action': 'ADD_LABELS',
                'labels': [(id, ['TRASH']) for id in selectedHeadersIds]}
        sendToServer(data)

      headers = getMessages(state['account'],position, height,
                            excludedLabels=excludedLabels,
                            includedLabels=includedLabels,
                            afterAction={'action':state['action'],
                                         'messageIds':selectedHeadersIds})
      numOfHeaders = getMessagesFunc(position, height, excludedLabels,
                                     includedLabels, True)
      return state

    elif k == ord('l'):
      # Various label related features.
      k = stdscr.getch()
      if k == ord('l'):
        # Show the labels on the highlighted message.
        showLabels = not showLabels
      else:
        if k == ord('u'):
          # Show unread messages.
          excludedLabels = ['SPAM', 'TRASH']
          includedLabels = ['UNREAD']
        elif k == ord('i'):
          # Show messages in the inbox (default)
          excludedLabels = ['SPAM', 'TRASH']
          includedLabels = ['INBOX']
        elif k == ord('s'):
          # Show sent messages.
          excludedLabels = []
          includedLabels = ['SENT']
        elif k == ord('t'):
          # Show the trash.
          excludedLabels = ['SPAM']
          includedLabels = ['TRASH']
        position = 0
        headers = getMessagesFunc(position, height, excludedLabels,
                                  includedLabels, False)
        numOfHeaders = getMessagesFunc(position, height, excludedLabels,
                                       includedLabels, True)

    elif k == ord('/'):
      # Do a search.
      searchTerms = getInput(stdscr, "Enter search terms: ", height, width)
      if searchTerms:
        results = search(account, searchTerms)
        getMessagesFunc = (lambda a, b, c, d, e:
                           getMessages(account, a, b, excludedLabels=c,
                                                      includedLabels=d,
                                                      query=results,
                                                      returnCount=e))
        position = 0
        headers = getMessagesFunc(position, height, excludedLabels,
                                  includedLabels, False)
        numOfHeaders = getMessagesFunc(position, height, excludedLabels,
                                       includedLabels, True)
        state['getMessagesFunc'] = getMessagesFunc
        state['searchTerms'] = searchTerms
      curses.curs_set(0)

    elif k == ord('c'):
      # Clear search terms.
      if searchTerms:
        getMessagesFunc = (lambda a, b, c, d, e:
                           getMessages(account, a, b, excludedLabels=c,
                                                      includedLabels=d,
                                                      returnCount=e))
        searchTerms = None
        position = 0
        headers = getMessagesFunc(position, height, excludedLabels,
                                  includedLabels, False)
        numOfHeaders = getMessagesFunc(position, height, excludedLabels,
                                       includedLabels, True)

    elif k == ord('v'):
      # View attachments.
      attachments = getAttachments(mkService(account), selectedHeader)
      headers = getMessagesFunc(position, height, excludedLabels,
                                  includedLabels, False)
      if attachments:
        state = {
            'action': 'VIEW_ATTACHMENTS',
            'account': account,
            'cursor_y': cursor_y,
            'position': position,
            'getMessagesFunc': getMessagesFunc,
            'searchTerms': searchTerms,
            'continue': True,
            'attachments': attachments
        }
        return state

    elif k == ord('\t'):
      # Toggle between accounts.
      account = next(switcher)
      getMessagesFunc = (lambda a, b, c, d, e:
                         getMessages(account, a, b, excludedLabels=c,
                                                    includedLabels=d,
                                                    returnCount=e))
      searchTerms = None
      position = 0
      headers = getMessagesFunc(position, height, excludedLabels,
                                includedLabels, False)
      numOfHeaders = getMessagesFunc(position, height, excludedLabels,
                                     includedLabels, True)

    elif k == ord('q'):
      # Quit.
      state = {'continue': False}
      return state

    if numOfHeaders == 0:
      for i in range(height - 2):
        stdscr.addstr(i, 0, ' ' * width)
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
        stdscr.attron(curses.color_pair(1))
        if cursor_y == i and h.messageId in selectedHeadersIds:
          stdscr.attron(curses.color_pair(4))
          stdscr.attron(curses.A_BOLD)
          stdscr.addstr(i, 0, display)
          if (width - l1) > 0:
            stdscr.addstr(i, l1, " " * (width - l1))
          stdscr.attroff(curses.A_BOLD)
          stdscr.attroff(curses.color_pair(4))
        elif cursor_y == i:
          stdscr.attron(curses.color_pair(3))
          stdscr.attron(curses.A_BOLD)
          stdscr.addstr(i, 0, display)
          if (width - l1) > 0:
            stdscr.addstr(i, l1, " " * (width - l1))
          stdscr.attroff(curses.A_BOLD)
          stdscr.attroff(curses.color_pair(3))
        elif h.messageId in selectedHeadersIds:
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
      if numOfHeaders < height - 2:
        for i in range(numOfHeaders, height - 1):
          stdscr.addstr(i, 0, " " * width)

    # Render status bar
    StatusBarInfo(
        account,
        includedLabels,
        excludedLabels,
        selectedHeader,
        searchTerms,
        numOfHeaders,
        0,  # totalMessages not used currently
        position + cursor_y + 1,
        showLabels).mkStatusBar(stdscr, height, width)

    if state:
      if 'action' in state:
        if state['action'] == 'SAVED_ATTACHMENT':
          putMessage(stdscr, height, width, "Attachment saved successfully.")
          state['action'] = ''

    if k == 'm0':
      # Follow up on composing a new message. Ask for the subject.
      subject = getInput(stdscr, "Subject: ", height, width)
      if subject:
        state = {'action': 'NEW',
                 'account': account,
                 'cursor_y': cursor_y,
                 'position': position,
                 'continue': True,
                 'to': state['to'],
                 'subject': subject}
        return state
      else:
        state.pop('action', None)
      stdscr.addstr(height - 1, 0, ' ' * (width - 1))
      curses.curs_set(0)
    # Refresh the screen
    stdscr.refresh()

    # Wait for next input
    k = stdscr.getch()

# <---
# <---

# ---> Post and Preprocessing functions

# ---> Postprocessing


def postDelete(state, service, messageIds):
  '''
  Modify labels on remote db after deleting.

  Args:
    state: The state of the program.
    service: The google API sevice object.
    messagedIds: List of message ids which were 
    deleted.

  Returns:
    None
  '''
  # Remove unread label from Google servers.
  logger.info('Modify labels in remote DB: + "TRASH", - "UNREAD".')
  if state['action'] == 'DELETE':
    body = {'ids': messageIds,
            'removeLabelIds': ['UNREAD'],
            'addLabelIds': ['TRASH']}
  elif state['action'] == 'MARK_AS_READ':
    body = {'ids': messageIds,
            'removeLabelIds': ['UNREAD'],
            'addLabelIds': []}
  elif state['action'] == 'TRASH':
    body = {'ids': messageIds,
            'removeLabelIds': [],
            'addLabelIds': ['TRASH']}
  account = state['account']
  try:
    service(account).users().messages().batchModify(
        userId='me', body=body).execute()
  except errors.Error as e:
    logger.debug(e)


def postSend(service, event, sender, draftId, **kwargs):
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
    header: If type is reply or foreward, this must be present.

  Returns: None
  '''

  try:
    with open(os.path.join(config.tmpDir, draftId), 'r') as f:
      message = createMessage(sender, f.read(), **kwargs)
    # Send the message.
    message = sendMessage(service(sender), sender, message)
    logger.info('sent message!')
    # Mark it as read if it wasn't already.
    if kwargs['type'] in ['REPLY', 'FORWARD']:
      header = kwargs['header']
      postRead(sender, event, service, header.messageId)
    # Clean up.
    os.remove(os.path.join(config.tmpDir, draftId))
    # Add message to local db.
    data = {'action': 'ADD_MESSAGES',
            'account': sender,
            'messageIds': [message['id']]}
    sendToServer(data)
    logger.info('data sent to server')
    event.set()
    # make this message more useful!
    # logger.info('Email sent successfully.')
  except Exception as e:
    # Something went wrong.
    logger.warning(e)


def postRead(account, event, service, messageId):
  '''
  Mark message as read after reading.

  Args:
    account: The currently selected account.
    event: threading.Event object - set it to true once local db has updated.
    service: The google API service object.
    messageId: The id of the highlighted message.

  Returns: 
    None
  '''
  # Mark message as read.
  # Remove 'UNREAD' label from local storage.
  logger.info('Removing label from local storage.')
  data = {'action': 'REMOVE_LABELS',
          'labels': [(messageId, ['UNREAD'])]}
  sendToServer(data)
  # Set event to true so that main thread can continue.
  event.set()
  # Remove unread label from Google servers.
  logger.info('Removing label from Google servers.')
  body = {'removeLabelIds': ['UNREAD'], 'addLabelIds': []}
  try:
    service(account).users().messages().modify(userId='me', id=messageId,
                                               body=body).execute()
  except errors.Error as e:
    logger.debug(e)

# <---

# ---> Preprocessing


def readMessage(service, messageId):
  '''
  Retrive a message from the server ready for reading.

  Args:
    service: The google API service object.
    messageId: The id of the message to retrive.

  Reurns:
    The message as a string ready for w3m.
  '''
  msg = service.users().messages().get(
      userId='me', id=messageId, format='raw').execute()
  msg = msg['raw']
  msg = base64.urlsafe_b64decode(msg).decode('utf-8')
  msg = email.message_from_string(msg, policy=email.policy.default)
  return msg.get_body(('html', 'plain',)).get_content()


def preSend(sender, state):
  '''
  Collect and organise various information 
  prior to actually sending the mail.

  Args:
    sender: Who will send the email.
    state: A dictonary with various information
      action: One of NEW, REPLY, FORWARD, REPLYTOALL.
      to: Who to send the mail to. Only needed if action is NEW or FORWARD.
      subject: Only if action is NEW.
      message: Present unless action is NEW. It is the message being replied
        to/forwarded.
      header: If action is not NEW, this must be present.

  Returns: 
    state: Same as input, and unless the user had a change of heart 
      a thread key.
      thread: Thread to be run later.
  '''
  if state['action'] == 'NEW':
    draftId = str(uuid4())
    header = None
    input = None

  elif state['action'] in ['REPLY', 'FORWARD', 'REPLYTOALL']:
    header = state['header']
    message, draftId = state['message'], header.messageId

    state['subject'] = mkSubject(header, state['action'])

    if state['action'] in ['REPLY', 'REPLYTOALL']:
      state['to'] = mkTo(sender, header, state['action'])

    # First format the message.
    formatedMessage = run(config.w3mArgs(), input=message,
                          encoding='utf-8', stdout=PIPE)

    # Rewrite mkReplyInfo/mkForwardInfo...
    input = addInfo(header, formatedMessage, state['action'])

  # Check that tmp file doesn't exist and remove if it does.
  if os.path.exists(os.path.join(config.tmpDir, draftId)):
    os.remove(os.path.join(config.tmpDir, draftId))

  # Open the formated message in vim.
  run(config.vimArgs(draftId), input=input, encoding='utf-8')

  # Check that tmp file exists ready to be sent.
  if os.path.exists(os.path.join(config.tmpDir, draftId)):
    type = state['action'] if state['action'] in [
        'NEW', 'FORWARD'] else 'REPLY'

    # Run confirmation loop.
    state = curses.wrapper(lambda x: drawConfirmationScreen(x, sender, state))

    # Make the thread.
    if state['action'] == 'SEND':
      finishedUpdatingLocalDb = Event()
      t = Thread(target=postSend,
                 args=(mkService, finishedUpdatingLocalDb, sender, draftId),
                 kwargs={'type': type,
                         'attachments': state['attachments'],
                         'to': state['to'],
                         'cc': state['cc'],
                         'bcc': state['bcc'],
                         'subject': state['subject'],
                         'header': header})
      state['thread'] = t
      state['event'] = finishedUpdatingLocalDb
    elif state['action'] == 'DO_NOT_SEND':
      state.pop('thread', None)
  else:
    state.pop('thread', None)
  return state


def addInfo(header, formatedMessage, type):
  '''
  Add a line containing infomation, and indent
  replies and forwarded messages.

  Args:
    header: the MessageInfo object of the mail being 
    replied to or forwarded.
    formatedMessage: The formatedMessage as output by w3m 
    as stdout.
    type: One of 'REPLY', 'REPLYTOALL', 'FORWARD'.
  Returns:
    A String consisting of the new message.
  '''
  lines = []
  for line in formatedMessage.stdout:
    if line == '\n':
      lines.append(line + '> ')
    else:
      lines.append(line)

  if type in ['REPLY', 'REPLYTOALL']:
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

  except errors.Error as e:
    logger.warning('An error occured while tring to save an attachment.')
    logger.warning('An error occurred: {}'.format(e))


def getAttachments(service, header):
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
  q = sendToServer(data)
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
          sendToServer(data)
          attachments.append(a)

    except errors.HttpError as e:
      logger.debug('An error occurred: {}'.format(e))
  if len(attachments) == 0:
    # In the future this can probably happen automagically.
    logger.info('Attempting to remove false positive attachment signal')
    data = {'action': 'REMOVE_FALSE_ATTACMENTS',
            'messageId': messageId}
    sendToServer(data)
    # q = s.query(MessageInfo).filter(MessageInfo.messageId == messageId)\
    #     .update({MessageInfo.hasAttachments: False},
    #             synchronize_session='evaluate')
    # s.commit()
    logger.info('Signal removed.')
  else:
    return attachments
# <---

# <---

# ---> Searching and filtering.


def search(account, searchTerms):
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
  sendToServer(data)
  data = {'action': 'GET_QUERY',
          'class': MessageInfo,
          'messageIds': messageIds}
  return [q.messageId for q in sendToServer(data)]


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


def sendToServer(data):
  host = socket.gethostname()
  port = config.port
  sock = socket.socket()
  bufferSize = 1024

  try:
    sock.connect((host, port))
    pickledData = pickle.dumps(data)
    sizeOfPickle = len(pickledData)
    numOfChunks = sizeOfPickle//bufferSize + 1
    sock.send(sizeOfPickle.to_bytes(4, 'big'))

    for i in range(numOfChunks):
      sock.send(pickledData[i*bufferSize: (i+1)*bufferSize])

    sizeOfResponse = int.from_bytes(sock.recv(4), 'big')
    response = b''

    while len(response) < sizeOfResponse:
      response += sock.recv(bufferSize)

    unpickledResponse = pickle.loads(response)
    sock.close()
    return unpickledResponse

  except:
    print('Could not connect to pmailServer, exiting.')
    logger.warning('Could not connect to pmailServer')
    sys.exit()


def setEscDelay():
  '''   
  This is needed so that when pressing ESCAPE to exit from the getInput
  function there is no noticable delay.
  '''
  os.environ.setdefault('ESCDELAY', '25')


def getMessages(account, position, height, **kwargs):
  query = kwargs.get('query', None)
  excludedLabels = kwargs.get('excludedLabels',[])
  includedLabels = kwargs.get('includedLabels',[])
  returnCount = kwargs.get('returnCount', False)
  afterAction = kwargs.get('afterAction', None)
  data = {'action': 'GET_MESSAGES',
          'account': account,
          'query': query,
          'position': position,
          'height': height,
          'excludedLabels': excludedLabels,
          'includedLabels': includedLabels,
          'count': returnCount,
          'afterAction': afterAction}
  return sendToServer(data)

def mainLoop():
  '''
  Main loop of the program. This loop processes the state 
  based on its 'action' and launches various subloops.
  '''
  # Initialise the state.
  # Varaible to pass state between this loop and the inner loop.
  logger.info('Starting main loop...')
  # state = None
  account = next(switcher)
  state = {'account': account}
  while True:

    # Run inner loop and update the state when it exits.
    state = curses.wrapper(
        lambda x: drawMessages(
            x, lambda a, b, c, d, e: getMessages(
                state['account'], a, b, excludedLabels=c,
                                        includedLabels=d,
                                        returnCount=e,
                                        afterAction={'action':'MARK_AS_READ' }
            ), state=state))
    # Process state.

    # Check we are not quitting.
    if state['continue'] == False:
      break

    # Read an email.
    elif state['action'] == 'READ':
      message = state['message']
      run(config.w3mArgs(), input=message, encoding='utf-8')
      finishedUpdatingLocalDb = Event()
      t = Thread(target=postRead,
                 args=(state['account'], finishedUpdatingLocalDb, mkService, state['messageId']))
      state['thread'] = t
      state['event'] = finishedUpdatingLocalDb

    # Send an email.
    elif state['action'] in ['REPLY', 'FORWARD', 'NEW', 'REPLYTOALL']:
      state = preSend(state['account'], state)

    # Move messages to Trash.
    elif state['action'] in ['DELETE', 'MARK_AS_READ', 'TRASH']:
      messageIds = state['messageIds']
      t = Thread(target=postDelete, name='DELETE',
                 args=(state, mkService, messageIds))
      state['thread'] = t

    # View Attachments.
    elif state['action'] == 'VIEW_ATTACHMENTS':
      attachments = state['attachments']
      state = curses.wrapper(lambda x: drawAttachments(
          x, account, state, attachments))


if __name__ == '__main__':
  setEscDelay()
  switcher = cycle(config.listAccounts())
  logger.setLevel(logging.DEBUG)
  mainLoop()
  preFetchedMessages = None

  # Clean up tmp files.
  for f in os.listdir(config.tmpDir):
    os.remove(os.path.join(config.tmpDir, f))
# <---

"""
vim:foldmethod=marker foldmarker=--->,<---
"""

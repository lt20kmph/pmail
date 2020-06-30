#!/usr/bin/python

# ---> Imports
from subprocess import run, PIPE
import email
import curses
import base64
from uuid import uuid4
from common import (mkService, s, Labels, HeaderInfo,
        removeLabels, addLabels, Session, logger, UserInfo)
from sendMail import createReply, createNewMessage, sendMessage
import os
from apiclient import errors
from threading import Thread 
# <---

# ---> Helper functions
# ADDRESS_CHARS = re.compile('[!#$%&\'*+-/=?^_`{|}~"(),:;<>@[\]]|[A-Za-z]|[0-9]') 

def getHeaders(excludedLabels=['SPAM','TRASH'],includedLabels=['SENT']):
    excludeQuery = s.query(Labels.messageId).filter(
            Labels.label.in_(excludedLabels))
    includeQuery = s.query(Labels.messageId).filter(
            Labels.label.in_(includedLabels))
    q = s.query(HeaderInfo)\
        .filter(~HeaderInfo.messageId.in_(excludeQuery))\
        .filter(HeaderInfo.messageId.in_(includeQuery))\
        .order_by(HeaderInfo.time.desc())
    return [h for h in q]


def readMessage(service, messageId):
    msg = service.users().messages().get(
        userId='me', id=messageId, format='raw').execute()
    msg = msg['raw']
    msg = base64ToString(msg).decode('utf-8')
    msg = email.message_from_string(msg, policy=email.policy.default)
    return msg.get_body(('html', 'plain',)).get_content()

def base64ToString(b):
    return base64.urlsafe_b64decode(b)

def markAsRead(service,messageId):
    # Remove 'UNREAD' label from local storage.
    logger.info('Removing label from local storage.')
    s = Session()
    removeLabels(s,[(messageId,['UNREAD'])])
    s.commit()
    Session.remove()
    # Remove unread label from Google servers.
    logger.info('Removing label from Google servers.')
    body = {'removeLabelIds': ['UNREAD'], 'addLabelIds': []}
    try:
        message = service().users().messages().modify(userId='me', id=messageId,
                                                body=body).execute()
    except errors.HttpError as e:
        print(e)
# <---

# ---> Curses functions
def setEscDelay():
    os.environ.setdefault('ESCDELAY', '25')

def getInput(stdscr,prompt,height,width):
    address = ""
    k, p = 0, len(prompt)
    stdscr.addstr(height-1, 0, ' ' * (width-1))
    stdscr.refresh()
    curses.curs_set(1)
    while k != '\n':
        l = len(address)
        stdscr.addstr(height-1,0,prompt + address)
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

def mkStatusBar(stdscr, currentAccount, height, width, includedLabels, excludedLabels):
    left = " \uf007 \uf054 "
    left = left + emailAddress +" \uf054 "
    mailbox = includedLabels[0] 
    leftLen = len(left)
    mbLen = len(mailbox)
    stdscr.attron(curses.color_pair(35))
    stdscr.addstr(height-2, 0, left)
    stdscr.attron(curses.A_BOLD)
    stdscr.addstr(height-2, leftLen, mailbox)
    stdscr.attroff(curses.A_BOLD)
    stdscr.addstr(height-2, leftLen+mbLen, " \uf054" + " "*(width -
        leftLen-mbLen-2))
    stdscr.attroff(curses.color_pair(35))

def drawInterface(stdscr, currentAccount, getHeadersFunc, **kwargs):
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
    stdscr.clear()
    stdscr.refresh()

    # Start colors in curses
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    for i in range(16):
        curses.init_pair(i, i, -1)
    for i in range(16, 32):
        curses.init_pair(i, i - 16, 3)
    for i in range(32,48):
        curses.init_pair(i, i - 32, 15)

    headers = getHeadersFunc()
    selectedHeader = headers[cursor_y]
    numOfHeaders = len(headers)
    excludedLabels = ['SPAM','TRASH']
    includedLabels = ['INBOX']

    # Loop where k is the last character pressed
    while True:
        # Initialization
        # stdscr.clear()
        height, width = stdscr.getmaxyx()

        if k == curses.KEY_DOWN:
            cursor_y = cursor_y + 1
            if cursor_y == height - 2:
                position = min(position + 1, numOfHeaders - height + 2)
        elif k == curses.KEY_UP:
            cursor_y = cursor_y - 1
            if cursor_y == -1:
                position = max(position - 1, 0)
        elif k == curses.KEY_NPAGE:
            position = min(position + height - 7, numOfHeaders - height + 2)
        elif k == curses.KEY_PPAGE:
            position = max(position - height + 7, 0)
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
        elif k == ord('d'):
            k = stdscr.getch()
            if k == ord('d'):
                # Delete message (move to trash).
                state = {'action': 'DELETE',
                         'cursor_y': cursor_y,
                         'position': position,
                         'continue': True,
                         'messageId': selectedHeader.messageId}
                return state
        elif k == ord('l'):
            k = stdscr.getch()
            if k == ord('u'):
                excludedLabels = ['SPAM', 'TRASH']
                includedLabels = ['UNREAD']
            elif k == ord('i'):
                excludedLabels = ['SPAM', 'TRASH']
                includedLabels = ['INBOX']
            elif k == ord('s'):
                excludedLabels = ['SPAM', 'TRASH']
                includedLabels = ['SENT']
            elif k == ord('t'):
                excludedLabels = ['SPAM']
                includedLabels = ['TRASH']
        elif k == ord('q'):
            state = {'continue': False}
            return state

        # Update list of messages.
        '''
        This might be too slow if db very large?? consider 
        running it in background thread with a deque to store 
        the current list.
        '''
        headers = getHeadersFunc(excludedLabels,includedLabels)
        numOfHeaders = len(headers)
        if numOfHeaders == 0:
            # Do something
            noMessages = "No messages found!"
            stdscr.addstr(height - 1, 0,noMessages)
            stdscr.addstr(height - 1, len(noMessages)," " * (width - 1))
        else:
            # Update line number.
            cursor_y = max(0, cursor_y)
            cursor_y = min(height-3, cursor_y, numOfHeaders - 1)
            # Update selected header.
            selectedHeader = headers[position + cursor_y]

            # statusbarstr = "Press 'q' to exit | STATUS BAR | Line: {} | Key: {}".format(cursor_y, k)

            for i, h in enumerate(headers[position:position + height - 2]):
                display, labels = h.display(15, width-31), str(h.showLabels())
                recipients,snippet = h.recipients, h.snippet
                l1, l2, l3, l4 = len(display), len(labels), len(recipients), len(snippet)
                stdscr.attron(curses.color_pair(4))
                if cursor_y == i:
                    stdscr.attron(curses.color_pair(20))
                    stdscr.attron(curses.A_BOLD)
                    stdscr.addstr(i, 0, display)
                    if (width - l1) > 0:
                        stdscr.addstr(i, l1, " " * (width - l1))
                    stdscr.attroff(curses.A_BOLD)
                    stdscr.attron(curses.color_pair(7))
                    stdscr.addstr(height-1, 0, (labels + ' :: ' + snippet)[:width-1])
                    try:
                        stdscr.addstr(height-1, l2+l4+2, " " * (width - l2 - 1-l4-2))
                    except:
                        pass
                    stdscr.attroff(curses.color_pair(7))
                    stdscr.attroff(curses.color_pair(20))
                else:
                    stdscr.addstr(i, 0, display)
                    if (width - l1) > 0:
                        stdscr.addstr(i, l1, " " * (width - l1))
                stdscr.attroff(curses.color_pair(4))
            if numOfHeaders < height - 2:
                for i in range(numOfHeaders, height - 1):
                    stdscr.addstr(i,0," " * width)

        # Render status bar
        mkStatusBar(stdscr, currentAccount, height,
                    width, includedLabels, excludedLabels)
# lsb = len(sb)
        # stdscr.attron(curses.color_pair(34))
        # stdscr.addstr(height-2, 0, sb)
        # stdscr.addstr(height-2, lsb, " " * (width - lsb))
        # stdscr.attroff(curses.color_pair(34))
        
        # Refresh the screen
        stdscr.refresh()

        # Wait for next input
        k = stdscr.getch()
# <---

W3MARGS = ["w3m", "-T", "text/html", "-s", "-o", "display_image=False", 
                "-o", "confirm_qq=False", "-o", "auto_image=False"]
TMPDIR_REPLIES = 'tmp/replies/'

def VIMARGS(messageId):
    # changefilepath - use directory tmp/replies/messageId
    return ["nvim", "-c", "set spell", "-c", "startinsert", "-c", 
            "f " + TMPDIR_REPLIES + messageId ]

def mkReplyInfo(header,formatedMessage):
    lines = []
    for line in formatedMessage.stdout:
        if line == '\n':
            lines.append(line + '>')
        else:
            lines.append(line)
    sender = header.parseSender()[0]
    replyInfo = "On " + header.timeForReply() + ' <' + sender + '> ' + 'wrote:'
    lines = ['\n\n',replyInfo,'\n\n>'] + lines
    return ''.join(lines)

# pointlessly(?) renaming things...
postRead = markAsRead

def postReply(service, myemail, header, messageId):
    # Make the message. 
    try:
        with open(TMPDIR_REPLIES + messageId, 'r') as f:
            message = createReply(myemail, header, f.read())
        # Send the message.
        sendMessage(service(), 'me', message)
        # Mark it as read if it wasn't already.
        markAsRead(service,messageId)
        # Clean up.
        os.remove(TMPDIR_REPLIES + messageId)
    except:
        # File didn't exist.
        pass

def postCompose(service, myemail, to, subject, messageId):
    # Make the message
    try:
        logger.debug('Trying to send a message.')
        with open(TMPDIR_REPLIES + messageId, 'r') as f:
            message = createNewMessage(myemail, to, subject, f.read())
        # Send the message.
        sendMessage(service(), 'me', message)
        # Clean up.
        logger.info('Removing temporary files.')
        os.remove(TMPDIR_REPLIES + messageId)
    except e:
        # File didn't exist.
        logger.warning(e)

def postDelete(service, messageId):
    # Add TRASH label to message
    logger.info('Adding label to local storage.')
    s = Session()
    addLabels(s,[(messageId,['TRASH'])])
    s.commit()
    Session.remove()
    # Remove unread label from Google servers.
    logger.info('Adding label to Google servers.')
    body = {'removeLabelIds': [], 'addLabelIds': ['TRASH']}
    try:
        message = service().users().messages().modify(userId='me', 
                id=messageId, body=body).execute()
    except errors.HttpError as e:
        print(e)

def mainLoop(currentAccount):
    # Initialise the state.
    # Varaible to pass state between this loop and the inner loop.
    state = None
    while True:

        # Run inner loop and update the state when it exits.
        state = curses.wrapper(
            lambda x: drawInterface(
                x, currentAccount, getHeaders, state=state))
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
            message,messageId = state['message'],header.messageId
            # First format the message.
            formatedMessage = run(W3MARGS, input=message, 
                    encoding='utf-8',stdout=PIPE)

            replyInfo = mkReplyInfo(header,formatedMessage)

            # seddedMessage = run(SEDARGS(replyInfo), 
            #         input=formatedMessage.stdout,
            #         encoding='utf-8', stdout=PIPE)
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
            # This seems unnecessary,
            # could probably take place in the inner thread.
            messageId = state['messageId']
            t = Thread(target=postDelete,
                    args=(mkService, messageId))
            state['thread'] = t 

if __name__ == '__main__':
    setEscDelay()
    emailAddress = (s.query(UserInfo)[0]).emailAddress
    mainLoop(emailAddress)

"""
vim:foldmethod=marker foldmarker=--->,<---
"""

# Pmail

## Introduction

Pmail aims to be a usable, terminal based client for Googles Gmail service
Pmail is built on top of the Gmail API, using python, hence the p.
Pmail is supposed to integrate well with other terminal utilities, it uses
[W3m][2] for parsing emails, [Vim][3] ([Neovim][4]) for editing and composing
emails and integrates [fzf][5] for fuzzy finding email addresses and as a file
picker for choosing attachments.
As of now I haven't tested with other programs in place of
these but in principle it should be possible to use other programs in their
places.

The motivation to develop Pmail comes from a growing frustration with getting
[mutt][6] and the related msmpt/offlineimap configuration functional.

Pmail does not aim to implement all features available through the API, the
current set of features is listed below.
Of course Pmail is heavily inspired
by [mutt][6] but aims to be a much simpler more usable client for Gmail users.

## Features

- Send, receive, reply, forward emails.
- Keyboard driven interface with vimish bindings.
- Lightweight.
- View emails using W3m.
- Compose emails with Vim.
- Fuzzy search through contacts using fzf, no need for an address book.
- Sort messages according with Gmails label system.
- Manipulate labels easily. (mark as read, move to trash, etc..)
- Separate client and server programs.

Pmail implements a client/server pair. The server is supposed to be run in the
background (for example via a systemd service) and it serves two purposes.
First it is supposed to keep a local database containing information about the
users mailbox in sync with the remote version kept by Google.
Second, it handles all database related functionality for the client.
The advantage of this is it allows the use of a sqlite database 
since concurrency issues can be handled between different threads of the same
program quite easily using Lock objects from pythons threading module. 
The local database is not a full copy of the remote inbox, it only stores 
information contained in the header fields of the emails (more or less).
If you want to read an email then it must be downloaded and so a network
connection is required.

## Installation instructions

At the moment Pmail is still in development and still has a few issues but it
needs testing. If you would like to test it out you should follow the following
instructions.

### Setup Gmail API

(Instructions valid as of July 2020.

1. Go to the [Quickstart guide][1] and click on the 'Enable the Gmail API
button.
2. Agree to the terms and conditions, select 'Desktop App' if it asks you for
the type of application and finally click the 'Download client configuration
button at the end.
3. Save the 'credentials.json' file somewhere safe.

After setting up the API, clone this repository and edit the example
configuration with your details. You can leave every thing as it is, the
important thing is to make sure you provide the details for at least one Gmail
account and the location of the related credentials.json file from the API.
When you finished save this file as 'config.yaml'.

Finally run pmailServer.py, and a Google window will open up (or a link will
appear in your terminal) asking you to confirm the relevant permissions.  If
everything went successfully after a few minutes you should have synced a local
copy of your mailbox and you can run the runClient.py and the client should
start up and you should see a list of your messages.

### Dependencies

You will also need to install W3m, vim and fzf if you wish to use all the
features of Pmail.
You will also require the following python packages:

- google-api-python-client 
- google-auth-httplib2 
- google-auth-oauthlib
- sqlalchemy
- yaml

These can be install with pip or however else you like to install python
modules.

## Usage Instructions

Use the arrow keys or j/k to scroll up and down through the message list.
You can also use PAGEUP/PAGEDOWN keys to scroll faster.
The selected email is highlighted as you scroll.
The following key bindings are available.

    RETURN - Read the selected email
    r - Reply
    f - forward an email
    g - Reply to group/Reply to all
    m - Compose a new email
    v - View attachments
    dd - Move mail to trash and mark as read
    dt - Move mail to trash but do not read
    dr - Mark as read but leave in the inbox
    ll - Toggle label visibility on and off
    lu - Show messages with unread label
    li - Only show messages with inbox label (default)
    ls - Show messages with sent label
    lt - Show messages in the trash
    / - Do a search
    c - Clear search filter
    SPACE - select email (can be used to select multiple emails)
    TAB - switch between accounts if you have more than one configured
    q - quit

Before finally sending an email a confirmation screen will be shown. On this
screen various options are available, but they are presented on the interface.
On the attachments screen, you can either press q to quit or s to save the
attachment to your downloads directory in the configuration file.

## Notes

If the local database gets too big scrolling can get sluggish.
I might implement some kind of prefetching system to get around this in the
future, but for now I have found it sufficient to only keep fairly recent emails
synced in the local database.
You can choose how much history you want to sync up by setting the
associated value in the configuration file.

When a search is executed a list of matching messages is retrieved directly from
Google - not by querying the local database - and the corresponding message
information is added to the local database.
This is probably not ideal - it means if you do a search with a large amount of
matches it can be quite slow and it can cause your local database to grow quite
allot.
On the other hand if you want to increase the amount of historical messages with
information stored locally you can just do a search for 'newer_than:4y', where
'4y' is any time period you like.
The search is compatible with any keyword search exactly the same as the usual
Gmail searching capabilities and hence its quite powerful.

pmailServer accepts an argument via a flag '-n'. The argument should be the
email address for one of your configured accounts. When run like this
pmailServer will return the number of currently unread messages in your inbox.

For example:

    ./pmailServer.py -n youremail@gmail.com

Would return the number of currently unread mail in youremails inbox, this is
potentially useful in scripts.

## Security considerations

YOU ARE RESPONSIBLE FOR YOU OWN SECURITY. Keep your credentials.json file
somewhere safe, possibly encrypted.
After the first the pmailServer also stores a token.pickle file this file
confirms that you have agreed to give permission to Pmail to send and modify
emails. 
Also keep this file safe.
Communications between the server and client parts of the program is incredibly
primitive and no form of encryption is currently implemented. Therefore, do no
attempt to run the client/server over any network you do not completely trust

## Limitations and TODO

- If database gets too large then scrolling is sluggish.
- The algorithm to detect attachments is unreliable.
- Handle searches with large number of results differently.
- Improve error handling and logging. 


[1]: https://developers.google.com/gmail/api/quickstart/python
[2]: http://w3m.sourceforge.net/
[3]: https://www.vim.org/
[4]: https://neovim.io/
[5]: https://github.com/junegunn/fzf
[6]: http://www.mutt.org/

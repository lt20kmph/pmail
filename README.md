# Pmail

Simple TUI mail client for Gmail.

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
[Mutt][6] and the related msmpt/offlineimap configuration functional.

Pmail does not aim to implement all features available through the API, the
current set of features is listed below.
Of course Pmail is heavily inspired
by [Mutt][6] but aims to be a much simpler more usable client for Gmail users.

### Obligatory screenshot

![screenshot][screenshot]

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

### Dependencies

You will also need to install W3m, vim and fzf if you wish to use all the
features of Pmail.
You will also require the following python packages:

    google-api-python-client 
    google-auth-httplib2 
    google-auth-oauthlib
    sqlalchemy

These can be installed with pip or however else you like to install python
modules.


### Setup Gmail API

(Instructions valid as of July 2020.) You will need to do this step for each
account you wish to use.

1. Go to the [Quickstart guide][1] and click on the 'Enable the Gmail API
button.
2. Agree to the terms and conditions, select 'Desktop App' if it asks you for
the type of application and finally click the 'Download client configuration
button at the end.
3. Save the `credentials.json` file somewhere safe.

#### Setup Gmail PubSub (optional)

This is an optional step which is only needed if you wish to enable push/pull
update notifications via GClouds PubSub interface. See [here][7] for detailed
instructions about how to set this up.

In summary what you need to do is this:

1. Install the pubsub client:

    pip install --upgrade google-cloud-pubsub

   You will need to create authentication credentials for the pubsub client,
   follow the instructions [here][8]. Save the resulting `credentials.json`
   file somewhere safe.

2. Create a pubsub topic called `pmail` for the project which is associated
   with API (if you followed the quickstart guide, this will be called
   something like `quickstart-xxxxxxxxxxxxx`) 
3. Create a subscription alled `pmail-update`, set the delivey type to `pull`.
4. Grant publish privileges to `gmail-api-push@system.gserviceaccount.com`.

### Install Pmail

#### Method 1: Using pip (recommended)

Run the following command:

    pip install pmail-tui

#### Method 2: Clone this repo

Make sure you have all of the dependencies installed and then:

    git clone https://github.com/lt20kmph/pmail

#### Method 3: From the AUR

Not supported yet

### Configure

Pmail looks for config files in the following locations in order of
preference:

    $HOME/.config/pmail/config.yaml
    ../config.yaml

To copy the included example config file to `$HOME/.config/pmail/config.yaml`
run the following:

    python -m pmail --mk-config

You can safely ignore most of the configuration options but you will need to
fill out your relevant details in the accounts section.

**For the pubsub to work (optional)** you will **need** to fill in the
relevant settings with the authentication and project name.

Also you might need to change `nvim` to `vim` under `editor` depending on your
preference.

### Getting Started

First we need to start the server. Run Pmail in server mode: 

    python -m pmail -m server

If everything is working, a Google window will open up (or a link will appear
in your terminal) asking you to confirm the relevant permissions. At this
point you may have to find the advanced options to 'allow unsafe apps'. If
everything went successfully after a few minutes (or longer, depending on how
much history you are syncing, controlled by the 'sync_from' option in the
config file) you should have synced a local copy of your mailbox and then you
can start Pmail in client mode, in a separate terminal window: 

    python -m pmail -m client

The client should start up and you should see a list of your messages, and you
can start deleting/sending/forwarding emails.

## Usage Instructions

Use the arrow keys or j/k to scroll up and down through the message list.
You can also use PAGEUP/PAGEDOWN keys to scroll faster.
The selected email is highlighted as you scroll.
The following key bindings are available.

    RETURN - Read the selected email
    r - Reply
    f - Forward an email
    a - Reply to group/Reply to all
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
    SPACE - Select email (can be used to select multiple emails)
    TAB - Switch between accounts if you have more than one configured
    b[n] - Switch to nth mailbox, for n in [1,..,9]
    bu - Start unified mailbox mode
    gg - Go to top of message list
    G - Go to bottom of message list
    CTRL U - Scroll up one page
    CTRL D - Scroll down one page
    H - Move cursor to first visible messsage
    M - Move cursor to central visible message
    L - Move cursor to last visible message
    q - Quit

Before finally sending an email a confirmation screen will be shown. On this
screen various options are available, but they are presented on the interface.
On the attachments screen, you can either press 'q' to quit or 's' to save the
attachment to your downloads directory in the configuration file.

## Notes

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

pmail can also be run with a flag '-n' and an account id.  When run like this
pmail will return an int corresponding to the number of unread mails in the
mail box of the account corresponding to the id provided.

For example, if you had the following in your `config.yaml`:

    accounts:
        yourname@gmail.com:
            id: 'ID'
            name: 'Wonderful Person'
            credentials: 'credentials.json'

then running:

    python -m pmail -n ID 

would return the number of unread mails in the mailbox for
`yourname@gmail.com`. This is potentially useful for scripts.

### Attachments

In order to correctly (more or less) detect which messages have attachments,
when pmail is first run, it will create a new hidden label called `ATTACHMENT`
which it will add to all existing messages with attachments and also create a
filter which will add this label to all new incoming messsages with
attachements. This means that pmail will display the attachments icon on any
messages which have the paperclip icon in the gmail web interface.

## Security considerations

YOU ARE RESPONSIBLE FOR YOU OWN SECURITY. Keep your credentials.json file
somewhere safe, possibly encrypted.
After the first run, Pmail stores a token.pickle file this file
confirms that you have agreed to give permission to Pmail to send and modify
emails. 
Also keep this file safe.
Communications between the server and client parts of the program is incredibly
primitive and no form of encryption is currently implemented. Therefore, do no
attempt to run the client/server over any network you do not completely trust

## Limitations and TODO

- [ ] There are some strange bugs which need to be investigated.
- [ ] Handle searches with large number of results differently.
- [ ] Improve error handling and logging (partially done, but can still be
    improved). 

[1]: https://developers.google.com/gmail/api/quickstart/python
[2]: http://w3m.sourceforge.net/
[3]: https://www.vim.org/
[4]: https://neovim.io/
[5]: https://github.com/junegunn/fzf
[6]: http://www.mutt.org/
[screenshot]: https://raw.githubusercontent.com/lt20kmph/pmail/master/scrot.png "Screenshot"
[7]: https://developers.google.com/gmail/api/guides/push 
[8]: https://cloud.google.com/pubsub/docs/reference/libraries 

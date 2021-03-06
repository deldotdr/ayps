"""
@author Dorian Raymer <deldotdr@gmail.com>
@author Dave Foster <dfoster@asascience.com>
@brief Asynchronous Python Shell
Useful extensions to the twisted.conch manhole using the Stdio transport.

@note This is a rough starting point for a potentially solid useful tool.
"""

import os
import re
import sys 
import tty
import math
import termios
import rlcompleter
import traceback

import attr

from twisted.application import service
from twisted.internet import stdio
from twisted.internet import error
from twisted.conch.insults import insults
from twisted.conch import manhole, recvline
from twisted.python import filepath
from twisted.python import text
from twisted.python.compat import iterbytes

from . import __version__

CTRL_A = '\x01'
CTRL_E = '\x05'
CTRL_R = "\x12"
CTRL_Q = "\x11"
ESC = "\x1b"

PROMPT_HISTORY = { True  : ("><> ", "... "),
                   False : ("--> ", "... ") }

def get_virtualenv():
    if 'VIRTUAL_ENV' in os.environ:
        virtual_env = os.path.join(os.environ.get('VIRTUAL_ENV'),
                        'lib',
                        'python%d.%d' % sys.version_info[:2],
                        'site-packages')
        return "[environ: %s]" % virtual_env
    return "[environ: system]"


@attr.s
class HistoryFile(object):
    maxlines = attr.ib(2500)
    filename = attr.ib(".ayps_history")
    directory = attr.ib()
    fpath = attr.ib(init=False)

    lines = None
    _file = None
    _drop = False
    _last = ""

    def __attrs_post_init__(self):
        self.lines = self.load()


    @directory.default
    def homedir(self):
        return os.environ["HOME"]

    @fpath.default
    def homedir(self):
        path = os.path.join(self.directory, self.filename)
        return filepath.FilePath(path)

    @property
    def len(self):
        return len(self.lines)

    def load(self):
        lines = []
        if self.fpath.exists():
            self.close()
            try:
                lines = self.fpath.getContent().split("\n")[-self.maxlines:]
            except Exception as e:
                print "HistoryFile: Load Error %s" % str(e)
        else:
            f = self.fpath.create()
            f.close()
        self.open()
        return lines

    def save(self):
        self.close()
        self.fpath.setContent("\n".join(self.lines[-self.maxlines:]))
        self.open()

    def open(self):
        if self._file is None:
            self._file = self.fpath.open("a")
        return self._file

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None

    def appendModeGet(self):
        return not self._drop

    def appendModeSet(self, onOff):
        self._drop = not onOff
        return onOff

    def appendModeToggle(self):
        return self.appendModeSet(self._drop)

    def append(self, line):
        self.lines.append(line)
        self.open().write(line + "\n")

    def lineReceived(self, line):
        if self._drop:
            return
        if self._last != line:
            self.append(line)
            self._last = line


class PreprocessedInterpreter(manhole.ManholeInterpreter):
    """
    """

    def __init__(self, handler, locals=None, filename="<console>", preprocess={}):
        """
        Initializes a PreprocessedInterpreter.

        @param preprocess   A dict mapping Regex expressions (which match lines) to
                            callables. The callables should take a single parameter (a
                            string with the line) and return either None or a string to
                            send to the interpreter. If None is returned, the callable
                            is assumed to have handled it and it is not sent to the
                            interpreter.
        """
        self._preprocessHandlers = preprocess
        manhole.ManholeInterpreter.__init__(self, handler, locals, filename)

    def addPreprocessHandler(self, regex, handler):
        self._preprocessHandlers[regex] = handler

    def delPreprocessHandler(self, regex):
        del(self._preprocessHandlers[regex])

    def push(self, line):
        """
        pre parse input lines
        """
        newline = line
        for regex, handler in self._preprocessHandlers.items():
            mo = regex.match(line)
            if mo != None:
                retval = handler(line)
                if retval == None:
                    return False        # handled, all good
                newline = retval
                break

        #if line and line[-1] == '?':
        #    line = 'obj_info(%s)' % line[:-1]
        return manhole.ManholeInterpreter.push(self, newline)


class ConsoleManhole(manhole.Manhole):
    ps = PROMPT_HISTORY[True]

    def initializeScreen(self):
        """@todo This should show relevant and useful development info:
         - python version
         - dependencies
          o versions
          o install path
         - virtualenv (if used)

        @todo Dependency info will be listed in the setup file
        """
        self.history_append = True      # controls appending of history
        self.historysearch = False
        self.historysearchbuffer = []
        self.historyFail = False # self.terminal.reset()
        self.historyFile = HistoryFile()

        self.terminal.write('Ayps: Asynchronous Python Shell\r\n')
        self.terminal.write('If you can read this, a twisted reactor is running...\r\n')
        self.terminal.write('\r\n')
        self.terminal.write('%s \r\n' % __version__)
        self.terminal.write('%s \r\n' % get_virtualenv())
        self.terminal.write('[process: %s@%s.%d] \r\n' % (os.getlogin(), os.uname()[1], os.getpid()))
        self.terminal.write('\r\n')
        #self.printHistoryAppendStatus()
        self.terminal.write(self.ps[self.pn])
        self.setInsertMode()

    def _deliverBuffer(self, buf):
        """
        Overwrites bug in twisted:
        https://github.com/twisted/twisted/pull/421#pullrequestreview-21012599
        """
        if buf:
            for ch in iterbytes(buf[:-1]):
                self.characterReceived(ch, True)
            self.characterReceived(buf[-1], False)

    def handle_TAB(self):
        try:
            self.__handle_TAB()
        except Exception, e:
            print "handle_TAB error"
            print e
            exc_type, exc_value, exc_traceback = sys.exc_info()
            traceback.print_tb(exc_traceback, limit=1, file=sys.stdout)
            print "*** print_exception:"
            traceback.print_exception(exc_type, exc_value, exc_traceback, limit=2, file=sys.stdout)
            print "*** print_exc:"
            traceback.print_exc()
            print "*** format_exc, first and last line:"
            formatted_lines = traceback.format_exc().splitlines()
            print formatted_lines[0]
            print formatted_lines[-1]

    def __handle_TAB(self):
        completer = rlcompleter.Completer(self.namespace)
        def _no_postfix(val, word):
            return word
        completer._callable_postfix = _no_postfix
        head_line, tail_line = self.currentLineBuffer()
        search_line = head_line
        cur_buffer = self.lineBuffer
        cur_index = self.lineBufferIndex

        def find_term(line):
            chrs = []
            attr = False
            for c in reversed(line):
                if c == '.':
                    attr = True
                if not c.isalnum() and c not in ('_', '.'):
                    break
                chrs.insert(0, c)
            return ''.join(chrs), attr

        search_term, attrQ = find_term(search_line)

        if not search_term:
            return manhole.Manhole.handle_TAB(self)

        if attrQ:
            matches = completer.attr_matches(search_term)
            matches = list(set(matches))
            matches.sort()
        else:
            matches = completer.global_matches(search_term)

        def same(*args):
            if len(set(args)) == 1:
                return args[0]
            return False

        def progress(rem):
            letters = []
            while True:
                to_compare = []
                for elm in rem:
                    if not elm:
                        return letters
                    to_compare.append(elm.pop(0))
                letter = same(*to_compare)
                if letter:
                    letters.append(letter)
                else:
                    return letters

        def group(l):
            """
            columns is the width the list has to fit into
            the longest word length becomes the padded length of every word, plus a
            uniform space padding. The sum of the product of the number of words
            and the word length plus padding must be less than or equal to the
            number of columns.
            """
            p = os.popen('stty size', 'r')
            rows, columns = map(int, p.read().split())
            p.close()
            l.sort()
            number_words = len(l)
            longest_word = len(max(l)) + 2
            words_per_row = int(columns / (longest_word + 2)) - 1
            number_rows = int(math.ceil(float(number_words) / words_per_row))

            grouped_words = [list() for i in range(number_rows)]
            for i, word in enumerate(l):
                """
                row, col = divmod(i_word, number_rows)
                row is the index of element in a print column
                col is the number of the col list to append to
                """
                r, c = divmod(i, number_rows)
                grouped_words[c].append(pad(word, longest_word))
            return grouped_words

        def pad(word, full_length):
            padding = ' ' * (full_length - len(word))
            return word + padding

        def max(l):
            last_max = ''
            for elm in l:
                if len(elm) > len(last_max):
                    last_max = elm
            return last_max

        if matches is not None:
            rem = [list(s.partition(search_term)[2]) for s in matches]
            more_letters = progress(rem)
            n = len(more_letters)
            lineBuffer = list(head_line) + more_letters + list(tail_line)
            if len(matches) > 1:
                #match_str = "%s \t\t" * len(matches) % tuple(matches)
                #match_rows = text.greedyWrap(match_str)
                groups = group(matches)
                line = self.lineBuffer
                self.terminal.nextLine()
                self.terminal.saveCursor()
                for row in groups:
                    s = '  '.join(map(str, row))
                    self.addOutput(s, True)
                if tail_line:
                    self.terminal.cursorBackward(len(tail_line))
                    self.lineBufferIndex -= len(tail_line)
            self._deliverBuffer(more_letters)

    def handle_QUIT(self):
        # XXX put a confirmation state here: "Really quit?"
        self.terminal.write('Bye!')
        # write reset to terminal before connection close OR
        # use os.write to fd method below?
        # self.terminal.write("\r\x1bc\r")
        self.terminal.loseConnection()
        # os.write(fd, "\r\x1bc\r")
        # then what?

    def _old_history_save_connectionLost(self, reason):

        # save the last 2500 lines of history to the history buffer
        # need a new mechanism to make no_history configurable 
        try:
            outhistory = "\n".join(self.historyLines[-2500:])
            f = open(os.path.join(os.environ["HOME"], '.ayps_history'), 'w')
            f.writelines(outhistory)
            f.close()
        except (IOError, TypeError):
            # i've seen sporadic TypeErrors when joining the history lines - complaining
            # about seeing a list when expecting a string. Can't figure out how to reproduce
            # it consistently, but it deals with exiting the shell just after an error in the
            # REPL. In any case, don't worry about it, and don't clobber history.
            pass

    def connectionLost(self, reason):
        self.historyFile.save()

        self.factory.shellQuit()
        if not reason.check(error.ConnectionDone):
            reason.printTraceback()

    def handle_CTRLR(self):
        if self.historysearch:
            self.findNextMatch()
        else:
            self.historysearch = True
        self.printHistorySearch()

    def handle_CTRLQ(self):
        self.history_append = not self.history_append;
        history_append = self.historyFile.appendModeToggle()
        self.ps = PROMPT_HISTORY[history_append]
        self.printHistoryAppendStatus()
        self.drawInputLine()

    def printHistoryAppendStatus(self):
        self.terminal.write('\r\n')
        self.terminal.write('History appending is ')
        #if self.history_append:
        if self.historyFile.appendModeGet():
            self.terminal.write('ON')
        else:
            self.terminal.write('OFF')
        self.terminal.write('. Press Ctrl+Q to toggle.\r\n')

    def handle_RETURN(self):
        """
        Handles the Return/Enter key being pressed. We subvert HistoricRecvLine's
        behavior here becuase it is insufficient, and call the only other override
        that matters, in RecvLine.
        """
        self.stopHistorySearch()

        # only add the current line buffer to the history if it a) exists and b) is distinct
        # from the previous history line. You don't want 10 entries of the same thing.
        # ---
        # This doesn't work if the history is empty...?
        # Dorian
        if self.lineBuffer:
            curLine = ''.join(self.lineBuffer)
            #if self.history_append and self.historyLines[-1] != curLine:
            #self.historyLines.append(curLine)
            self.historyFile.lineReceived(curLine)
        #self.historyPosition = len(self.historyLines)
        self.historyPosition = self.historyFile.len
        return recvline.RecvLine.handle_RETURN(self)

    def handle_BACKSPACE(self):
        if self.historysearch:
            if len(self.historysearchbuffer):
                self.historyFail = False
                self.historysearchbuffer.pop()
                self.printHistorySearch()
            # should vbeep on else here
        else:
            manhole.Manhole.handle_BACKSPACE(self)

    def handle_UP(self):
        self.stopHistorySearch()
        manhole.Manhole.handle_UP(self)

    def handle_DOWN(self):
        self.stopHistorySearch()
        manhole.Manhole.handle_DOWN(self)

    def handle_INT(self):
        self.stopHistorySearch()
        self.historyPosition = len(self.historyLines)
        #self.historyPosition = self.historyFile.len
        manhole.Manhole.handle_INT(self)

    def handle_RIGHT(self):
        self.stopHistorySearch()
        manhole.Manhole.handle_RIGHT(self)

    def handle_LEFT(self):
        self.stopHistorySearch()
        manhole.Manhole.handle_LEFT(self)

    def handle_ESC(self):
        self.stopHistorySearch()

    def stopHistorySearch(self):
        wassearch = self.historysearch
        self.historysearch = False
        self.historysearchbuffer = []
        if wassearch:
            self.printHistorySearch()

    def printHistorySearch(self):
        self.terminal.saveCursor()
        self.terminal.index()
        self.terminal.write('\r')
        self.terminal.cursorPos.x = 0
        self.terminal.eraseLine()
        if self.historysearch:
            if self.historyFail:
                self.addOutput("failing-")
            self.addOutput("history-search: " + "".join(self.historysearchbuffer) + "_")
        self.terminal.restoreCursor()

    def findNextMatch(self):
        # search from history search pos to 0, uninclusive

        historyslice = self.historyLines[:self.historyPosition-1]
        #historyslice = self.historyFile.lines[:self.historyPosition-1]
        cursearch = ''.join(self.historysearchbuffer)

        foundone = False
        historyslice.reverse()
        for i in range(len(historyslice)):
            line = historyslice[i]
            if cursearch in line:
                self.historyPosition = len(historyslice) - i
                self.historysearch = False

                if self.lineBufferIndex > 0:
                    self.terminal.cursorBackward(self.lineBufferIndex)
                self.terminal.eraseToLineEnd()

                self.lineBuffer = []
                self.lineBufferIndex = 0
                self._deliverBuffer(line)

                # set x to matching coordinate
                matchidx = line.index(cursearch)
                self.terminal.cursorBackward(self.lineBufferIndex - matchidx)
                self.lineBufferIndex = matchidx

                self.historysearch = True
                foundone = True
                break

        if not foundone:
            self.historyFail = True

    def characterReceived(self, ch, moreCharactersComing):
        if self.historysearch:
            self.historyFail = False
            self.historyPosition = len(self.historyLines)
            #self.historyPosition = self.historyFile.len
            self.historysearchbuffer.append(ch)
            self.findNextMatch()
            self.printHistorySearch()
        else:
            manhole.Manhole.characterReceived(self, ch, moreCharactersComing)

    def connectionMade(self):
        manhole.Manhole.connectionMade(self)
        self.historyLines = self.historyFile.lines
        self.historyPosition = self.historyFile.len

        preprocess = { re.compile(r'^.*\?$') : self.obj_info }
        self.interpreter = PreprocessedInterpreter(self, self.namespace, preprocess=preprocess)

        self.keyHandlers.update({
            CTRL_A: self.handle_HOME,
            CTRL_E: self.handle_END,
            CTRL_R: self.handle_CTRLR,
            CTRL_Q: self.handle_CTRLQ,
            ESC: self.handle_ESC,
            })

    def _old_history_init(self):
        # read in history from history file on disk, set internal history/position
        try:
            f = open(os.path.join(os.environ["HOME"], '.ayps_history'), 'r')
            self.historyLines = [line.rstrip('\n') for line in f.readlines()]
            f.close()
            self.historyPosition = len(self.historyLines)
        except IOError:
            pass

    def obj_info(self, item, format='print'):
        """Print useful information about item."""
        # Item is a string with the ? trailing, chop it off.
        item = item[:-1]

        # now eval it
        try:
            item = eval(item, globals(), self.namespace)
        except Exception, e:
            self.terminal.write('\r\n')
            self.terminal.write(str(e))
            return None

        if item == '?':
            self.terminal.write('Type <object>? for info on that object.')
            return
        _name = 'N/A'
        _class = 'N/A'
        _doc = 'No Documentation.'
        if hasattr(item, '__name__'):
            _name = item.__name__
        if hasattr(item, '__class__'):
            _class = item.__class__.__name__
        _id = id(item)
        _type = type(item)
        _repr = repr(item)
        if callable(item):
            _callable = "Yes"
        else:
            _callable = "No"
        if hasattr(item, '__doc__'):
            maybe_doc = getattr(item, '__doc__')
            if maybe_doc:
                _doc = maybe_doc
            _doc = _doc.strip()   # Remove leading/trailing whitespace.
        info = {'name':_name, 'class':_class, 'type':_type, 'repr':_repr, 'doc':_doc}
        if format is 'print':
            self.terminal.write('\r\n')
            for k,v in info.iteritems():
                self.terminal.write("%s: %s\r\n" % (str(k.capitalize()), str(v)))

            self.terminal.write('\r\n\r\n')
            return None
        elif format is 'dict':
            raise ValueError("TODO: no work")
            return info

class Controller(service.Service):


    def __init__(self, namespace=None, stop_reactor_on_quit=False):
        """
        """
        if namespace is None:
            namespace = {}
        self.namespace = namespace
        self.fd = sys.__stdin__.fileno()
        self.fdout = sys.__stdout__.fileno()
        self.standardIO = None
        self.oldSettings = None
        self.stop_reactor_on_quit = stop_reactor_on_quit


    def startService(self):
        service.Service.startService(self)
        self._prepareSettings()

        serverProtocol = insults.ServerProtocol(ConsoleManhole, self.namespace)
        serverProtocol.factory = self
        self.serverProtocol = serverProtocol

        # XXX for live experimentation with the protocol
        self.namespace['_ayps_serverProtocol'] = serverProtocol

        self.standardIO = stdio.StandardIO(serverProtocol)

    def _prepareSettings(self):

        self.oldSettings = termios.tcgetattr(self.fd)
        # tty.setraw(fd)
        tty.setraw(self.fd, termios.TCSANOW) # when=now

        # stdout fd
        outSettings = termios.tcgetattr(self.fdout)
        outSettings[1] = termios.OPOST | termios.ONLCR
        termios.tcsetattr(self.fdout, termios.TCSANOW, outSettings)

    def _restoreSettings(self):
        termios.tcsetattr(self.fd, termios.TCSANOW, self.oldSettings)
        # if terminal write reset doesnt work in handle QUIT, use this
        os.write(self.fd, "\r\x1bc\r") # is this necessary?

    def shellQuit(self):
        """
        Event called by server protocol when user quits shell.
        """
        self._restoreSettings()
        if self.stop_reactor_on_quit:
            from twisted.internet import reactor
            reactor.stop()
        else:
            os.write(self.fd, 'Shell exited. Press Ctrl-c to stop process\n')
        

    def stopService(self):
        service.Service.stopService(self)
        self.standardIO.loseConnection()


if __name__ == "__main__":
    import sys
    from twisted.internet import reactor
    #sys.path.insert(0, '')
    shell = Controller(stop_reactor_on_quit=True)
    shell.startService()
    reactor.run()


import os
import cgi
import ast
import sys
import time
import types
import jinja2
import urllib
import timeit
import webapp2
import logging
import datetime
import traceback
import __builtin__

from decimal import Decimal
from itertools import chain
from functools import partial
from cStringIO import StringIO
from collections import defaultdict

from webapp2_extras import json
from google.appengine.ext import ndb
from google.appengine.api import mail
from google.appengine.api import users

from models import Log
from models import Algorithm

JINJA_ENVIRONMENT = jinja2.Environment(
    loader = jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape']
)

OWNERS = [
    'laffra@gmail.com',
    'test@example.com',
]


class LogHandler(webapp2.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if user and user.email() in OWNERS:
            days = self.request.get('days') or 1
            when = datetime.datetime.utcnow() - datetime.timedelta(days=int(days))
            key = ndb.Key('Python Algorithms', 'scrap')
            query = Log.query(ancestor=key).filter(Log.date > when).order(-Algorithm.date)
            rows = query.fetch(None)
            logs = [
                (
                    n,
                    log.date,
                    log.msg.split('\n')[0][5:],
                    '\n'.join(log.msg.strip().split('\n')[1:])
                ) 
                for n,log in enumerate(rows)
            ]
            template = JINJA_ENVIRONMENT.get_template('log.html')
            self.response.write(template.render(locals()))
        else:
            template = JINJA_ENVIRONMENT.get_template('login.html')
            login = users.create_login_url('/log')
            self.response.write(template.render(locals()))


class UsersHandler(webapp2.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if user and user.email() in OWNERS:
            key = ndb.Key('Python Algorithms', 'scrap')
            query = Log.query(ancestor=key)
            if not self.request.get('all'):
                query = query.filter(Log.author != user)
            rows = query.fetch(None)
            names = [log.msg.split('\n')[0][5:] for log in rows ]
            names = sorted(set(map(lambda name: name.split(' ')[0], names)))
            names = filter(lambda name: '@' in name, names)
            self.response.write('%d<p>' % len(names) + '<br>'.join(names))
        else:
            template = JINJA_ENVIRONMENT.get_template('login.html')
            login = users.create_login_url('/users')
            self.response.write(template.render(locals()))


class TutorialDashboardHandler(webapp2.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if user and user.email() in OWNERS:
            now = datetime.datetime.utcnow()
            when = now - datetime.timedelta(days=int(1))
            key = ndb.Key('Python Algorithms', 'scrap')
            query = Algorithm.query(ancestor=key).filter(Algorithm.date > when).order(Algorithm.date)

            def isTutorial(name):
                return name and '__temp__' in name and not '%2B' in name and not 'Preview:' in name and not 'Preview%3A' in name
            last = {}
            for edit in query.fetch(None):
                if isTutorial(edit.name):
                    last['%s_%s' % (edit.name, edit.author.email())] = edit

            def time(edit):
                seconds = (now - edit.date).seconds
                if seconds >= 3600:
                    return '%dh' % (seconds/ 3600)
                elif seconds >= 60:
                    return '%dm' % (seconds/ 60)
                else:
                    return '%ds' % (1 + seconds)

            def recency(edit):
                seconds = (now - edit.date).seconds
                if seconds >= 3600:
                    return 'hours'
                elif seconds >= 60:
                    return 'minutes'
                else:
                    return 'seconds'

            editMap = defaultdict(list)
            for edit in reversed(last.values()):
                editMap[ edit.name[8:].replace('+', ' ') ].append(
                    (
                        edit.date,
                        time(edit),
                        recency(edit),
                        edit.author.email().split('@')[0],
                        edit.author.email(),
                        'show?' +  urllib.urlencode({
                            'name': 'Preview: ' + edit.name[8:].replace('+', ' '),
                            'share': 'false',
                            'script': '# Author: %s\n\n%s' % (edit.author, edit.script),
                            'viz': edit.viz
                        })
                    )
                ) 

            edits = reversed(sorted(editMap.iteritems(), key=lambda edit: min([e[0] for e in edit[1]])))
            when = datetime.datetime.utcnow() - datetime.timedelta(days=int(1))
            template = JINJA_ENVIRONMENT.get_template('dashboard.html')
            self.response.write(template.render(locals()))
        else:
            template = JINJA_ENVIRONMENT.get_template('login.html')
            login = users.create_login_url('/log')
            self.response.write(template.render(locals()))


class CloseHandler(webapp2.RequestHandler):
    def get(self):
        self.response.headers.add_header("Content-Type", "text/html")
        self.response.write(JINJA_ENVIRONMENT.get_template('close.html').render(locals()))


class ShowHandler(webapp2.RequestHandler):
    def loadScript(self, name, user=None):
        query = Algorithm.query(ancestor=ndb.Key('Python Algorithms', 'scrap')) \
            .filter(Algorithm.name == name) \
            .order(-Algorithm.date)
        algo = None
        for algo in query.fetch(None):
            if algo.public or not user or algo.author == user:
                break
        if algo:
            logging.info('Load script '+str(algo.date))
            return algo.name, algo.script, algo.viz, algo.author
        else:
            logging.info('No algo found for '+name)
            return name, "# Cannot find: '"+name+"'", "", user


    def get(self):
        edit = self.request.get('edit') == 'true'
        tabs = self.request.get('tabs') == 'true'
        delay = self.request.get('delay') or '1'
        visualize = self.request.get('visualize') == 'true'
        script = urllib.unquote(self.request.get('script') or '')
        viz = urllib.unquote(self.request.get('viz') or '')
        name = self.request.get('name')
        url = 'https://pyalgoviz.appspot.com/show?name=%s' % name
        user = users.get_current_user()
        author = user
        if user or visualize:
            logout = users.create_logout_url("/")
            if name and not script and not viz:
                _, script, viz, author = self.loadScript(name, user)
            editor_width = 1150 if tabs else 600
            editor_height = 640 if tabs else 450
            jstabs = "true" if tabs else "false"
            html = 'edit_tabs.html' if tabs else 'visualize.html' if visualize else 'edit.html'
            template = JINJA_ENVIRONMENT.get_template(html)
            html = template.render(locals())
            self.response.write(html)
            self.response.headers.add_header("Content-Type", "text/html")
            logging.info('Response: %d bytes' % len(html))
        else:
            template = JINJA_ENVIRONMENT.get_template('login.html')
            next = '/show?edit=%s&name=%s' % (edit, name)
            if visualize:
                next = '/close'
            login = users.create_login_url(next)
            self.response.write(template.render(locals()))
            self.response.headers.add_header("Content-Type", "text/html")


class LinkHandler(ShowHandler):
    def get(self):
        name = self.request.get('name')
        user = users.get_current_user()
        _, _, _, author = self.loadScript(name, user)
        self.response.write(
            "<style>body{font-size:25px; font-family:Arial; color:maroon;}</style>" + \
            "<b>" + name + "</b> by " + author.email() +  \
            "<p><a href='/show?tabs=true&name="+name+"'>open with tabs</a> " + \
            "<p><a href='/show?name="+name+"'>open regular</a>" 
        )


class RunHandler(webapp2.RequestHandler):
    def post(self):
        name = self.request.get('name')
        script = self.request.get('script')
        viz = self.request.get('viz')
        if script == 'none':
            algo = Algorithm.query(ancestor=ndb.Key('Python Algorithms', 'scrap')) \
                .filter(Algorithm.name == name) \
                .filter(Algorithm.public == True) \
                .order(-Algorithm.date).get()
            if algo:
                script = algo.script
                viz = algo.viz
        result = Executor(
            script, viz,
            self.request.get('showVizErrors') == 'true',
        )
        author = users.get_current_user()
        info('Ran %s "%s":\n%s' % (author, name, script))
        self.response.write(json.encode({
            'error': result.error,
            'events': result.events,
        }))


def loadfile(name):
    path = os.path.join(os.path.split(__file__)[0], name)
    with open(path) as file:
        return file.read().decode('utf-8')

class SourceHandler(webapp2.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if user and user.email() in OWNERS:
            name = self.request.get('name') or 'main.py'
            files = [
                (n, 'sourceLink selected' if n == name else 'sourceLink')
                for n in [
                    'main.py', 'models.py', 
                    'index.html', 'edit.html', 'source.html',
                    'all.css', 'pyalgoviz.css',
                    'all.html',
                ]
            ]
            source = loadfile(name)
            source = source.replace('&','&&').replace('<','&lt;')
            template = JINJA_ENVIRONMENT.get_template('source.html')
            self.response.write(template.render(locals()))


class UpdateHandler(webapp2.RequestHandler):
    def post(self):
        user = users.get_current_user()
        self.response.content_type = 'text/plain'
        if user and user.email() in OWNERS:
            name = self.request.get('name')
            name = 'test.py'
            script = self.request.get('script')
            try:
                path = os.path.join(os.path.split(__file__)[0], name)
                with open(path, "w") as file:
                    file.write(script)
                msg = 'Saved source: %s' % name
            except Exception as e:
                msg = 'Could not save source: %s' % e
            self.response.write(msg)
        else:
            self.response.write('No user?')


class SaveHandler(webapp2.RequestHandler):
    def post(self):
        author = users.get_current_user()
        self.response.content_type = 'application/json'
        try:
            algo = Algorithm(parent = ndb.Key('Python Algorithms', 'scrap'))
            algo.author = author
            algo.script = self.request.get('script')
            algo.viz = self.request.get('viz')
            algo.name = self.request.get('name')
            algo.public = False
            algo.put()
            # notify(author, 'save', algo.name, algo.script, algo.viz)
            msg = 'Script was successfully saved by %s as "%s"' % (author.email(), algo.name)
            info(msg)
            info(algo.script)
        except Exception as e:
            msg = 'Could not save script: %s' % e
        self.response.write(json.encode({'result': msg}))


class LoadHandler(ShowHandler):
    def get(self):
        name = self.request.get('name').replace(' ', '+')
        author = users.get_current_user()
        try:
            query = Algorithm.query(ancestor=ndb.Key('Python Algorithms', 'scrap')) \
                .filter(Algorithm.author == author) \
                .filter(Algorithm.name == name) \
                .order(Algorithm.date)
            self.response.content_type = 'application/json'
            for algo in reversed(query.fetch(None)):
                self.response.write(json.encode({ 
                    'name': name, 
                    'script': algo.script, 
                    'viz': algo.viz
                }))
                info('loaded "%s", viz=%d bytes, script=%d bytes' % (
                    name, len(algo.viz), len(algo.script)
                ))
                return
            error('Could not load "%s"' % name);
            self.response.write(json.encode({ 
                'name': name, 
                'script': '',
                'viz': '',
            }))
        except Exception as e:
            msg = 'Cannot load "%s": %s' % (name,e)
            error(msg)
            self.response.write(json.encode({ 
                'error': msg
            }))


def info(msg):
    try:
        log = Log(parent = ndb.Key('Python Algorithms', 'scrap'))
        log.msg = msg
        log.put()
    except Exception as e:
        pass # print 'Could not log info "%s" due to %s' % (msg, e)
    try:
        logging.info(msg)
    except Exception as e:
        pass # print 'Could not log info "%s" due to %s' % (msg, e)

def error(msg):
    logging.error(msg)
    log = Log(parent = ndb.Key('Python Algorithms', 'scrap'))
    log.msg = 'ERROR:' + msg
    log.put()


def notify(user, action, name, script, viz):
    if user.email() not in OWNERS:
        subject = "PyAlgoViz - %s - %s" % (action, name)
        body = '%s\n\nhttp://pyalgoviz.appspot.com/show?name=%s\n\nScript:\n%s\n\nVisualization:\n%s' % (
            user.email(), 
            name.replace(' ','%20'),
            script,
            viz
        )
        mail.send_mail(user.email(), user.email(), subject, body)



class MainHandler(webapp2.RequestHandler):
    def get(self):
        template = JINJA_ENVIRONMENT.get_template('index.html')
        html = template.render({'algorithms': self.algorithms(), 'user':self.user()})
        self.response.headers.add_header("Content-Type", "text/html")
        self.response.write(html)
        logging.info('Response: %d bytes' % len(html))

    def user(self):
        return True

    def algorithms(self):
        return self.load((Algorithm.public == True))

    def load(self, filter):
        query = Algorithm.query(ancestor=ndb.Key('Python Algorithms', 'scrap')) \
            .filter(filter)
        def info(pair):
            n, algo = pair
            return (
                algo.name,
                algo.author.nickname(),
                algo.author.user_id(),
                algo.events or '[]',
                n,
                'not yet shared' if not algo.public else '',
            )
        algos = reversed(sorted(query.fetch(None), key=lambda algo: algo.date))
        algos = map(info, enumerate(algos))
        found = set()
        result = []
        for algo in algos:
            if algo[0] not in found:
                found.add(algo[0])
                result.append(algo)
        return sorted(result)


class UserHandler(MainHandler):
    def user(self):
        return False

    def algorithms(self):
        author = users.get_current_user()
        if author:
            return self.load(Algorithm.author == author)

GOOGLE_COLORS = [
    "#0140CA", # blue
    "#DD1812", # red
    "#FCCA03", # orange
    "#0140CA", # blue
	"#16A61E", # green
    "#DD1812", # red
]

HD = False

DEMO_WIDTH = 1920 if HD else 1200
DEMO_HEIGHT = 1080 if HD else 700

DEDICATION_WIDTH = 1720 if HD else 1000
JOKE_WIDTH = 1720 if HD else 1000

DEMO_HTML_CSS    = '''

body, html { font-family:Arial; font-size: 25px; margin:0px; color:#777; }
h1 {text-align:center}
#main { width:%s; padding:0px; margin-left:auto; margin-right:auto; }
iframe { overflow: hidden; }
img { margin-top:25px; margin-bottom: 25px; }
.arrow {
    border: 1px #aaa solid; padding: 10px;
    background: #0140CA; color: white;
    text-decoration: none; font-size: 15px; 
}
.left { float: left; background: #16A61E; }
.right { float: right; background: #FCCA03; }
.demo_outer { }
.demo { border: 1px #aaa solid; border-width: 1px 0; padding: 10px;
        font-size:25px; background:lightyellow;}
.demo button { font-size:22px; color:white; background: #0140CA; }
.dedication { position: relative; z-index: 100; padding:20px 50px; 
        width: %spx; margin-top: -50px; border: 3px #DD1812 solid; }
.joke { padding:20px 50px; width: %spx; margin: 50px; border: 3px #DD1812 solid; }
.joke pre { font-family: Arial }
.persons { -webkit-column-count: 3; }
.person { text-align: center; }
.person img { margin: 0; }
''' % (DEMO_WIDTH, DEDICATION_WIDTH, JOKE_WIDTH)

DEMO_HTML_HEADER = "<html><head><style>" + loadfile("all.css") + "</style>" + \
    "<style>%s</style></head><body><div id=main>" % DEMO_HTML_CSS

DEMO_HTML_FOOTER = loadfile("all.html") + "</div></body></html>"

FRAME_WIDTH = 1920 if HD else 1200
FRAME_HEIGHT = 975 if HD else 700

DEMO_SCRIPT = '''
    <script>
        var currentDemo = "Xtra%%20-%%20Demos%%20-%%20BubbleSort";
        var currentSlide = 1
        function demo(demoID) {
            document.getElementById(currentDemo).innerHTML = 
                "<div class=demo>" +
                "<b>" + currentDemo.replace(/%%20/g,' ') + "</b>" + 
                "<p><button name=" + currentDemo + " onclick='demo(this.name)' " + 
                "tabs=true>LOAD THE DEMO</button> " + 
                "</div>";
            document.getElementById(demoID).innerHTML = 
                "<iframe width=%s height=%s src=show?tabs=true&name="+demoID+"></iframe>";
            currentDemo = demoID;
            document.location = "demo#" + demoID;
        }
        document.addEventListener('onkeydown', function(e) {
            var keyCode = e.keyCode;
            alert(keyCode)
        }, false);
    </script>
''' % (FRAME_WIDTH, FRAME_HEIGHT)

DEMO_SLIDES = "http://image.slidesharecdn.com/howigotmyjobatgoogle-140412130045-phpapp02/95/"

DEMO_HELP = '''
<ul>
 <li> <b>__lineno__</b>
 <li> <b>beep</b>(frequency, milliseconds)
 <li> <b>text</b>(x, y, txt, size=13, font='Arial', color='black')
 <li> <b>line</b>(x1, y1, x2, y2, color='black', width=1)
 <li> <b>rect</b>(x, y, w, h, fill='white', border='black')
 <li> <b>circle</b>(x, y, radius, fill='white', border='black')
 <li> <b>arc</b>(cx, cy, innerRadius, outerRadius, startAngle, endAngle, color='black')
 <li> <b>barchart</b>(x, y, w, h, items, highlight=-1, scale=1, fill='black', border='black')
</ul>
'''

PRINT_LAYOUT = False

class DemoHandler(ShowHandler):
    linkCount = 0

    def get(self):
        self.response.headers.add_header("Content-Type", "text/html")

        def label(space=True):
            if PRINT_LAYOUT:
                return "<hr>"
            html = "&nbsp;&nbsp;&nbsp;"
            if self.linkCount > 0:
                html += arrow("right", "Previous", "#label_%s" % (self.linkCount-1))
                html += "&nbsp;&nbsp;&nbsp;&nbsp;"
            self.linkCount += 1
            if self.linkCount > 1:
                html += arrow("left", "Next", "#label_%s" % self.linkCount)
            html += "<a name=label_%s></a>" % (self.linkCount)
            html += "<br>" * 7 if space else ""
            return html

        def arrow(clz, text, url):
            return "<a class='arrow " + clz + "' href=" + url +">" + text + "</a>"

        def h1(value):
            return label() + "<h1>%s</h1>" % (value)

        def html(value):
            return "<div style='width:1280px'>%s</div>" % (value)

        def img(src, w=DEMO_WIDTH, h=DEMO_HEIGHT, showLabel=True):
            return (label() if showLabel else "") + ("<br>"*3 if self.linkCount>1 else "") + \
                    "<center><img height=%s width=%s src=%s></center>" % (h,w,src)

        def persons(details):
            html = "<div class=persons>"
            for name, picture, site, w, h in details:
                html += "<div class=person>" + img("http://"+picture, w, h, False)
                html += "<br>" + link(name,"http://"+site) + "</div>"
            return html + "</div>" + "<br>"*7

        def joke(text):
            return label() + "<p><div class=joke><h1>Joke Time</h1><center><pre>" + text + \
                    "</pre></center></div>"

        def link(text, url, prefix='', postfix=''):
            return prefix + "<a target=_blank href=" + url +">" + text + "</a>" + postfix

        def algo(name):
            id = name.replace(' ', '%20')
            return "<a name=" + id +"></a><div id='" + id + "' class=demo_outer><div class=demo>" + \
                "<p><button name=" + id + " onclick='demo(this.name)' " + \
                "tabs=true>\"" + name +"\"</button> " + \
                "</div></div><p>"

        self.response.write(''.join([
            DEMO_HTML_HEADER,

            h1("Fabulous Python Algorithm Visualization"),

            html(
                "<ul>" + \
                "<li>Introduction (2 min)" + \
                "<li>Develop a visualization for Bubble Sort (5 min)" + \
                "<li>Discuss architecture of PyAlgoViz (8 min)" + \
                "<li>Graph Algorithms (10 min)" + \
                "<li>Numerical Algorithms (10 min)" + \
                "<li>Q&A (10 min)" + \
                "</ul><p>"
            ),

            h1("Introduction"),

            html("<iframe src='http://pyalgoviz.appspot.com' width='1280' height='680'></iframe>"),

            h1("Let's Start with Bubble Sort (5 min)"),
                algo("Xtra - Demos - BubbleSort"),

                h1("Python Algorithm Visualization Primitives"),
                html(DEMO_HELP),

                algo("Sorting - BuzzSort"),

            h1("The Architecture of PyAlgoViz (8 min)"), 

                img(DEMO_SLIDES + "slide-4-1024.jpg"),  # Pycon poster - browser
                img(DEMO_SLIDES + "slide-5-1024.jpg"),  # Pycon poster - server
                img(DEMO_SLIDES + "slide-6-1024.jpg"),  # pseudo code for pyalgoviz

            h1("Graph Algorithms (10 min)"), 

                algo("Graphs - Dijkstra Shortest Path"),
                label(False),
                algo("Computational Geometry - Convex Hulls"),
                label(False),
                algo("Graphs - MST"),
                label(False),
                algo("Searching - BFS"),
                label(False),
                algo("Searching - DFS"),
                label(False),
                algo("Trees - AVL"),

            h1("Numerical Algorithms (10 min)"), 

                algo("Geometry - Pi Archimedes"),
                label(False),
                algo("Geometry - Pi Buffon"),
                label(False),
                algo("Numbers - Fibonnacci Generator"),
                label(False),
                algo("Numbers - Fibonacci / Golden Ratio"),
                label(False),
                algo("Numbers - Mandelbrot Set"),
                label(False),
                algo("Numbers - Prime Generator"),

            h1("Q&A (10 min)"), 


            "<br>" * 13,

            DEMO_SCRIPT,
            DEMO_HTML_FOOTER
        ]))

TUTORIAL_SCRIPT = '''
    <script>
        setTimeout(function() { 
            setPage(page, 'block');
            labelAlgos();
        }, 3000);
        function labelAlgos() {
            var pageNumbers = {};
            var pages = $('.tutpage');
            $.each(pages, function(n, page) {
              pageNumbers[page.title] = page.getAttribute('n');
            });
            for (title in pageNumbers) {
              var n = pageNumbers[title];
              $("li:contains('" + title + "')")
                  .click(function() { document.location = '/oscon?page=' + this.getAttribute('n'); })
                  .css('color', 'blue')
                  .css('cursor', 'pointer')
                  .css('text-decoration:hover', 'underline')
                  .attr('n', n)
            }
        }
        function getPage(n) {
            return document.getElementById('page-' + n)
        }
        function setPage(n, display) {
            var e = getPage(n);
            if (e) {
                e.style.display = display;
                var progressbar = document.getElementById('progressbar');
                var pageCount = $('.tutpage').length;
                var pageLink = '<a href="javascript:indexPage()">' + n + '/' + pageCount + '</a>';
                $('#progressbar').html('Page ' + pageLink + 
                        '&nbsp;&nbsp;&dash;&nbsp;&nbsp;' + e.title);
                var algo = $('#algo-' + n);
                algo.attr('src', (display == 'none') ? '' : algo.attr('url'));
            }
            return e;
        }
        function indexPage() {
            setPage(page, 'none');
            page = 2;
            setPage(page, 'block');
            history.pushState({}, 'Algorithms For Fun and Profit - ' + page, 'oscon?page=' + page);
        }
        function nextPage() {
            if (getPage(page + 1)) {
                setPage(page, 'none');
                page++;
                setPage(page, 'block');
                history.pushState({}, 'Algorithms For Fun and Profit - ' + page, 'oscon?page=' + page);
             }
        }
        function prevPage() {
            if (getPage(page - 1)) {
                setPage(page, 'none');
                page--;
                setPage(page, 'block');
                history.pushState({}, 'Algorithms For Fun and Profit - ' + page, 'oscon?page=' + page);
             }
        }
        function getURLParameter(name, defaultValue) {
            return decodeURIComponent(
                (new RegExp('[?|&]' + name + '=' + '([^&;]+?)(&|#|;|$)').exec(location.search)||[,""])[1].replace(/\+/g, '%20'))||defaultValue
        }
        var page = parseInt(getURLParameter('page', 1));
        setPage(page, 'block');
    </script>
'''

TUTORIAL_HTML_CSS    = '''
    body, html { font-family:Arial; font-size: 25px; margin:0px; color:#777; }
    h1,h2,h3 {100px; text-align:center;}
    .shadowText { text-shadow: -1px 0 black, 0 1px black, 1px 0 black, 0 -1px black; }
    table {margin-left: 100px;}
    td {margin:10px; padding-top:25px; border:1px solid #CCC;}
    #main { width:1280px; padding:0px; margin-left:auto; margin-right:auto; }
    iframe { overflow: hidden; }
    .hover { position: absolute; right:68px; top:15px; color:white;}
    img { }
    .arrow {
        border: 1px #aaa solid; padding: 10px;
        background: #0140CA; color: white;
        text-decoration: none; font-size: 15px; 
    }
    .next { float: right; margin-right: -4px; width:80px; background: #16A61E; text-align:center;}
    .previous { float: left; width:80px; background: #FCCA03; text-align:center;}
    #progressbar { width:1075; float:left; text-align: center; padding-top:7px;}
    .demo_outer { }
    #clock { margin: 100px -100px; }
    center { width:1280; }
    .algo { width:1280; height:1000px; }
    .demo button { font-size:22px; color:white; background: #0140CA; }
    .persons { -webkit-column-count: 3; }
    .person { text-align: center; }
    .person img { margin: 0; }
    .header { float: left; width:1280px; }
    .tutpage { float: left; width:1280px; display: none; }
    a { color: #777; }
'''

TUTORIAL_HTML_HEADER = "<html><head><style>" + loadfile("all.css") + "</style>" + \
    "<style>%s</style></head><body><div id=main>" % TUTORIAL_HTML_CSS


#########################################################################

TUTORIAL_BUBBLESORT = [
"BubbleSort", 
'''
def bubbleSort(L):
    for i in range(len(L) - 1, 0, -1): 
        for j in xrange(i):
            if L[j] > L[j+1]:
                L[j],L[j+1] = L[j+1],L[j]

from random import sample
data = sample(range(10), 10)

print 'before:', data, sorted(data) == data
bubbleSort(data)
print 'after: ', data, sorted(data) == data
''', 
'''



# This is our visualization plan:
#
#   1. play some sound
#   2. show the current value of "data"
#   3. show each value as a rect to make a bargraph
#   4. make the graph bottom-oriented 
#   5. show current values of "i" and "j" by coloring bars
#   6. use builtin barchart
#   7. show marker to show if algorithm is correct
'''
]

TUTORIAL_QUICKSORT = [
"QuickSort", 
'''
print "World"
''', 
'''
print "Hello"
'''
]

#########################################################################

TUTORIAL_FIZZBUZZ = [
"FizzBuzz", 
'''
def fizzbuzz(numbers):
    result = []
    for number in numbers:
        result.append('fizzbuzz')
        result.append('fizz')
        result.append('buzz')
        result.append(number)
    return result

            
expected = [
	1, 2, 'fizz', 4, 'buzz', 
    'fizz', 7, 8, 'fizz',  'buzz', 
    11, 'fizz', 13, 14, 'fizzbuzz'
]
assert fizzbuzz(range(1, 16)) == expected,  'Fizzbuzz Failed'
''', 
'''
for n in numbers:
    text(50, 25 + n*25, n, 20)

colors = {
    'fizz': 'green',
    'buzz': 'blue',
    'fizzbuzz': 'red',
}
for n,value in enumerate(expected):
    color = colors.get(value, 'black')
    text(150, (n+2)*25, value, 20, color=color)
    
for n,value in enumerate(result):
    color = colors.get(value, 'black')
    text(250, (n+2)*25, value, 20, color=color)

text(50, 12, 'numbers')
text(150, 12, 'expected')
text(250, 12, 'result')

text(400, 160, 'YOU', 35)
text(400, 200, 'PASSED' if result==expected else 'FAILED', 35)
text(400, 240, 'THE', 35)
text(400, 280, 'INTERVIEW', 35)
'''
]

#########################################################################

TUTORIAL_KNUTH_SHUFFLE = [
"Knuth Shuffle",
'''
import random

LEN = 10
original = range(LEN)
shuffled = []
for i in range(LEN):
    index = random.randrange(0, LEN-i)
    value = original[index]
    del original[index]
    shuffled.append(value)
''',
'''
X, Y1, Y2, D = 50, 120, 270, 40

text(20, Y1-20, 'Original list', 25)
for n,value in enumerate(original):
    color = 'red' if n==index else 'green' if n==i else 'white'
    rect(X+n*D, Y1+0*D, D-5, D-5, color)
    text(X+n*D+2, Y1+0*D+D/2, value, 15)

text(20, Y2-20, 'Shuffled List', 25)
for n,value in enumerate(shuffled):
    rect(X+n*D, Y2+0*D, D-5, D-5)
    text(X+n*D+2, Y2+0*D+D/2, value, 15)
'''
]


#########################################################################

TUTORIAL_ANAGRAM_CHECK = [
"Anagram Check",
'''
def is_anagram(s1, s2):
    #
	# s1 and s2 are an anagram if they consist
    # of the same rearranged characters
    #
    # fix the code below
    #
    return len(s1) == len(s2)

def unit_tests():
    samples = [
       ('secure', 'rescue', True),
       ('google', 'googol', False),
       ('conifer', 'fircone', True),
       ('ronald', 'donald', False),
    ]
    
    for s1,s2,expected in samples:
        anagram = is_anagram(s1, s2)
        print 'Test:', s1, s2
        assert anagram == expected, 'is_anagram is broken'

unit_tests()
''',
'''
label = 'OK' if anagram == expected else 'FAIL'
color = 'green' if anagram == expected else 'red'
text(30, 320, label, 20, 'Arial', color)

def show(s, y, label):
    text(30, y+20, label, 20, 'Arial', 'teal')
    text(100, y+20, list(s), 20, 'Arial', 'teal')
    text(300, y+20, sorted(s), 20, 'Arial', 'blue')
        
show(s1, 100, 's1:')
show(s2, 200, 's2:')
'''
]

#########################################################################

TUTORIAL_PALINDROME_CHECK = [
"Palindrome Check",
'''
def palindrome(s):
    #
    # Given a string, check if it is a palindrome.  
    #
    return s == s[::-1]
        
strings = [
   'acdc',
   'kayak',
   'deadmau5',
   'abba',
]
for s in strings:
	print '%s: %s' % (repr(s), palindrome(s))
''',
'''
def show(s, y, color, label):
    text(30, y+20, label, 20, 'Arial', color)
    for n,c in enumerate(s):
        rect(150+n*30, y, 25, 25)
        text(155+n*30, y+20, c, 20, 'Arial', color)

if s == s[::-1]:
    color = 'teal'
    line(40, 300, 50, 325, color, 5)
    line(50, 325, 90, 275, color, 5)
else:
    color = 'red'
    line(40, 275, 90, 325, color, 5)
    line(40, 325, 90, 275, color, 5)

show(s, 100, color, 'original:')
show(s[::-1], 200, color, 'reversed:')
'''
]

#########################################################################

TUTORIAL_PRIME_NUMBERS = [
"Prime Numbers",
'''
def isPrime(number):
    # this is a slow form of trial division, we can do better
    for k in range(2, number):
        if number % k == 0:
            return False
    return True

def getPrimes(count=50):
    for n in xrange(2, count+1):
        if isPrime(n):
            yield n        

primes = []
for p in getPrimes():
    primes.append(p)

expected = [2,3,5,7,11,13,17,19,23,29,31,37,41,43,47]
assert primes == expected, 'Assert error: isPrime is broken...'
''',
'''
X, Y, D = 50, 100, 40
text(X, 355, 'n = %d, k = %d' % (n, k), 30)
if n in primes:
    text(X, 405, '%d is prime' % n, 30)

for number in range(1, n+1):
    color = 'pink' if number in primes else 'lightyellow' 
    if number == k:
        color = 'red'
    y = (number - 1) / 10
    x = (number - 1) % 10
    rect(X+x*D, Y+y*D, D-5, D-5, color)
    text(X+x*D+2, Y+y*D+D/2, number, 15)

rect(X, 22, 395, 40, '#333')
text(X+30, 52, 'Prime Number Generator', 30, color='lightblue')
'''
]

#########################################################################

TUTORIAL_PERMUTATIONS = [
"Permutations",
'''
def permutations(s):
    if len(s) <= 1: 
        yield s
    else:
        for i in range(len(s)):
            for p in permutations(s[:i] + s[i+1:]):
                yield s[i] + p
        
input = 'ABCD'

for permutation in enumerate(permutations(input)):
    print permutation
print
''',
'''
number, perm = permutation

text(35, 70, 'Input:', 21)
for n,c in enumerate(input):
    color = 'orange' if c == perm[0] else 'lightyellow'
    rect(250 + n*30, 50, 25, 25, color)
    text(255 + n*30, 70, c, 21)
    
text(35, 170, 'Permutation %d:' % number, 21)
for n,c in enumerate(perm):
    rect(250 + n*30, 150, 25, 25, 'lavender')
    text(255 + n*30, 170, c, 21)
    line(262 + n*30, 150, 262 + input.index(c)*30, 75, '#AAA')
    
rect(35, 272, 290, 40, '#333')
text(45, 302, 'String Permutations', 30, color='lightblue')
'''
]

#########################################################################

TUTORIAL_FIBONACCI = [
"Fibonacci",
'''
def fibonacci():
    p,c = 1,1
    yield p
    yield c
    while True:
        c,p = p+c, c
        yield c
        
fib = fibonacci()
numbers = []
for number in range(1,50):
    numbers.append(fib.next())

print numbers
''',
'''
from math import pi

R,U,L,D = A = range(4)
dir,angle,x,y = D,pi,150,170
scale = min(10.0, 60.0/sum(numbers))
w = [10*n*scale for n in numbers]
for k in range(len(numbers)):
    if k == 0:
        x += w[k]; ax,ay = x+w[k],y
    elif k == 1:
        x += w[k]; ax,ay = x,y
    else:
        if dir == R:
            x += w[k-1]; y -= w[k-2]; ax,ay = x,y
        elif dir == U:
            x -= w[k-2]; y -= w[k]; ax,ay = x,y+w[k] 
        elif dir == L:
            x -= w[k]; ax,ay = x+w[k],y+w[k]
        elif dir == D:
            y += w[k-1]; ax,ay = x+w[k],y
    if w[k]>5:
        rect(x, y, w[k], w[k], border='#CCC')
        text(x+1, y+9, numbers[k], 10, 'Arial', '#CCC')
        arc(ax, ay, w[k]-3, w[k], angle, angle+pi/1.95, 'red')
    angle -= pi/2
    dir = A[(dir+1)%4]
    
rect(35, 370, 400, 50, '#444')
text(115, 405, 'The Golden Ratio', 30, 'Arial', 'gold')
text(135, 60, 'O = %.10f' % (float(numbers[-1])/numbers[-2]), 30)
text(142, 58, '|', 36)

y = 50
for n,p in enumerate(reversed(numbers)):
    size = max(1, 20 - n/1.5)
    text(470, y, p, size=size)
    y += size + 2
    
beep(len(numbers)*30, 3000)
'''
]

#########################################################################

TUTORIAL_PI = [
"Approximating Pi",
'''
import math

def pi_archimedes_approximation(n):
    edge_length_squared = 2.0
    edges = 4
    step = 1
    for i in range(n):
        edge_length_squared = 2 - 2 * math.sqrt(1 - edge_length_squared / 4)
        edges *= 2
        step += 1
    return edges * math.sqrt(edge_length_squared) / 2

print "PI = %s" % pi_archimedes_approximation(5)
''',
'''
import math
cx, cy, r, angle = 450, 270, 200, math.pi/4
colors = [ 'orange', 'red', 'blue', 'teal' ]
x1,y1 = cx + r*math.cos(angle), cy - r*math.sin(angle)

circle(cx, cy, r)
PI = (edges * math.sqrt(edge_length_squared) / 2)
text(10, 30, 'Step: %d' % step, 25)
text(10, 60, 'Number of sides: %d' % edges, 25)
text(10, 90, 'Pi: %s' % PI, 25)
text(10, 120, 'Error: %.10f' % (math.pi - PI), 25)

for edge in range(edges+1):
    x2,y2 = cx + r*math.cos(angle), cy - r*math.sin(angle)
    line(x1, y1, x2, y2, colors[step % 4], 3)
    line(cx, cy, x1, y1, '#AAA')
    x1,y1 = x2,y2
    angle += 2*math.pi/edges
    
beep(step * 300, 10)
'''
]

#########################################################################

TUTORIAL_RANDOM_PI = [
"Random Pi",
'''
from random import randint
from math import pi, sin, cos

W = 400		# surface width
H = 400 	# surface height
D = 25    	# half length of each needle
L = 100 	# 2X needle length

needles = []
touching = []

for n in range(600):
    x,y,a = randint(0,W), randint(0,H), randint(0,200)*pi/100
    x1,y1,x2,y2 = x-D*sin(a), y-D*cos(a), x+D*sin(a), y+D*cos(a)
    needles.append((x1,y1,x2,y2))
    if min(x1,x2)%L>=2*D and max(x1,x2)%L<=2*D:
        touching.append((x1,y1,x2,y2))

PI = 1.0*len(needles)/len(touching)
print len(needles), len(touching), PI


# See: https://www.youtube.com/watch?v=sJVivjuMfWA
''',
'''
beep(__lineno__*100, 1000)

text(W+45, 50, '%d random needles' % len(needles))
text(W+45, 70, '%d touching' % len(touching))
    
rect(W+35, 270, 140, 70, 'black')
text(W+55, 300, 'Buffon\\'s', 25, 'Arial', 'lavender')
text(W+55, 330, 'Needles', 25, 'Arial', 'lavender')

text(W+45, 200, 'PI = %s' % PI, 15)

rect(25, 25, W, H)

for x in range(0, W, L):
    line(x+25, 0+25, x+25, H+25, '#AAA')
    
for x1,y1,x2,y2 in needles:
    color = 'red' if (x1,y1,x2,y2) in touching else 'green'
    line(x1+25,y1+25,x2+25,y2+25, color, 1)
'''
]

#########################################################################

TUTORIAL_LINEAR_SEARCH = [
"Linear Search",
'''
from random import sample

def linearSearch(value, numbers):
    for n in range(len(numbers)):
        if value == numbers[n]:
            return n
    return -1

data = sample(range(40), 20)
test = sample(range(40), 5)

for value in test:
    print 'linear search for', value, '==>',
    print linearSearch(value, data)
''',
'''
barchart(100, 50, 340, 200, data, highlight=n, scale=5)

for n,x in enumerate(test):
    color = 'pink' if x == value else 'white'
    rect(100 + 70*n, 275, 60, 60, color)
    text(115 + 70*n, 300, x, 25)
    try:
        index = numbers.index(x)
    except ValueError:
        index = -1
    text(120 + 70*n, 325, index, 15)
'''
]

#########################################################################

TUTORIAL_BINARY_SEARCH = [
"Binary Search",
'''
from random import sample

def binary_search(value, numbers):
    min = 0; max = len(numbers) - 1
    while True:
        if max < min:
            return -1
        mid = (min + max) / 2
        if numbers[mid] < value:
            min = mid + 1
        elif numbers[mid] > value:
            max = mid - 1
        else:
            return mid

data = sorted(sample(range(40), 20))
test = sample(range(40), 5)

for value in test:
    print 'binary search for', value, '==>',
    print binary_search(value, data)
''',
'''
barchart(100, 50, 340, 200, data, highlight=mid, scale=5)

for n,x in enumerate(test):
    color = 'pink' if x == value else 'white'
    rect(100 + 70*n, 375, 60, 60, color)
    text(115 + 70*n, 400, x, 25)
    try:
        index = numbers.index(x)
    except ValueError:
        index = -1
    text(120 + 70*n, 425, index, 15)
    
def show(name, index, y, color):
    x = 125 + 15*index
    line(x, y, x, 260, color, 2)
    text(x+3, y+3, '%s = %d (%d)' % (name, index, data[index]))
    
show('mid', mid, 320, 'orange')
show('max', max, 340, 'red')
show('min', min, 300, 'blue')
'''
]

#########################################################################

TUTORIAL_BFS = [
"Breath First Search",
'''
tree = (
    ((None,6,(None,9,None)),10,((None,23,None),
    37,(None,44,None))),52,((None,56,None),68,
    (((None,79,None),87,None),89,((None,91,None),
    93,(None,94,None))))
)

def BFS(root, n):
    queue = [root]
    while queue:
        root = queue.pop(0)
        left, v, right = root
        if v == n: 
            return v
        queue.extend(filter(None, [left, right]))

for n in [9, 91, 44, 56, 79, 23, 94, -1]:
    print n, BFS(tree, n)
''',
'''
def showTree(tx, ty, px, py, w, node, depth):
    if not node: return
    color = 'orange' if node == root else 'teal'
    if px: line(px, py-5, tx, ty-5, '#AAA', 3)
    l, v, r = node
    showTree(tx-w/2-10, ty+49, tx, ty, w/2, l, depth+1)
    showTree(tx+w/2+10, ty+49, tx, ty, w/2, r, depth+1)
    circle(tx, ty-5, 20, color)
    text(tx-9, ty, v, 16, 'Arial', 'white')
    if color=="orange":
        beep(500+depth*500, 500)

showTree(260, 50, 0, 0, 250, tree, 1)

text(30, 330, 'BFS - Breath First Search', 30, color='navy')
text(30, 370, 'Search for %d' % n, 30, color='navy')
'''
]

#########################################################################

TUTORIAL_DFS = [
"Depth First Search",
'''
tree = (
    ((None,6,(None,9,None)),10,((None,23,None),37,(None,44,None))),
    52,((None,56,None),68,(((None,79,None),87,None),89,
    ((None,91,None),93,(None,94,None))))
)

def DFS(root, n):
    # Turn this BFS into DFS
    queue = [root]
    while queue:
        left, v, right = queue.pop(0)
        if v == n: 
            return v
        queue.extend(filter(None, [left, right]))

for n in [9, 91, 44, 56, 79, 23, 94, -1]:
    print n, DFS(tree, n)
''',
'''
def showTree(tx, ty, px, py, w, node, depth):
    if not node: return
    color = 'orange' if node==root else 'teal'
    if px: line(px, py-5, tx, ty-5, '#AAA', 3)
    l, v, r = node
    showTree(tx-w/2-10, ty+49, tx, ty, w/2, l, depth+1)
    showTree(tx+w/2+10, ty+49, tx, ty, w/2, r, depth+1)
    circle(tx, ty-5, 20, color)
    text(tx-9, ty, v, 16, 'Arial', 'white')
    if color=="orange":
        beep(500+depth*500, 500)

showTree(260, 50, 0, 0, 250, tree, 1)

text(30, 330, 'DFS - Depth First Search', 30, color='navy')
text(30, 370, 'Search for %d' % n, 30, color='navy')
'''
]

#########################################################################

TUTORIAL_GNOME_SORT = [
"Gnome Sort",
'''
import random

def kabouter_sort(data):
    n = 0
    while n < len(data):
        if n == 0: 
            n += 1
        if data[n] >= data[n - 1]: 
            n += 1
        else:
            data[n - 1], data[n] = data[n], data[n-1]
            n -= 1
        
data = random.sample(range(40), 30)

kabouter_sort(data)

# See: http://en.wikipedia.org/wiki/Gnome_sort
#
# Worst case performance		O(n^2)
# Best case performance			O(n)
# Average case performance		O(n^2)
# Worst case space complexity	O(1)
''',
'''
barchart(50, 100, 500, 250, data, highlight=n, scale=5)
'''
]

#########################################################################

TUTORIAL_INSERTION_SORT = [
"Insertion Sort",
'''
import random

def insertionSort(s):
    for i in range(1, len(s)):
        val = s[i]
        j = i - 1
        while (j >= 0) and (s[j] > val):
            s[j+1] = s[j]
            j = j - 1
        s[j+1] = val

data = random.sample(range(40), 30)
         
insertionSort(data)
print data

#
# Worst case performance		O(n^2)
# Best case performance			O(n)
# Average case performance		O(n^2)
# Worst case space complexity	O(n)
''',
'''
barchart(10, 20, 500, 140, data, highlight=i, scale=2.5)
text(530, 40, 'data')

w = 460/len(data)

def barX(index):
    return 40+index*w  

for n in range(len(data)):
    text(barX(n)-4, 180, n)
    
def show(name, index, y, color):
    x = barX(index)
    line(x, y, x, 185, color, 2)
    text(x+3, y+3, '%s = %d' % (name, index))

show('i', i, 220, 'blue')
show('j', j, 260, 'red')

beep(j * 50, 1000)
'''
]

#########################################################################

TUTORIAL_QUICK_SORT = [
"Quick Sort",
'''
import random

def qsort(L):
    if len(L) < 2: return L
    pivot = L[0]
    equal = filter(lambda n: n == pivot, L)
    less = filter(lambda n: n <  pivot, L)
    greater = filter(lambda n: n >  pivot, L)
    return qsort(less) + equal + qsort(greater)

data = [
   24, 30, 20, 15, 25, 1, 8, 7, 37, 16, 
   21, 2, 12, 22, 34, 33, 14, 38, 39, 18, 
   36, 28, 17, 4, 32, 13, 40, 35, 6, 5, 
]
         
result = qsort(data)

print data

# See: http://en.wikipedia.org/wiki/Quicksort
#
# Worst case performance		O(n2) (extremely rare)
# Best case performance			O(n log n)
# Average case performance		O(n log n)
# Worst case space complexity	O(n) (naive)
# 								O(log n) (Sedgewick 1978)
''',
'''
barchart(10, 20, 510, 90, data, highlight=data.index(pivot), scale=2)
text(530, 40, 'data')

pivotIndex = L.index(equal[0]) if equal[0] in L else -1
barchart(10, 120, 510, 90, L, highlight=pivotIndex, scale=2)
text(530, 150, 'current')

barchart(240, 220, 50,  90, equal, fill='yellow', scale=2)
barchart(10,  220, 220, 90, less, fill='darkgreen', scale=2)
barchart(300, 220, 220, 90, greater, fill='blue', scale=2)
text(530, 240, 'next')
text(245, 330, 'x = %d' % pivot, 16, color="teal")

barchart(10, 345, 510, 90, result, scale=2)
'''
]

#########################################################################

TUTORIAL_MERGE_SORT = [
"Merge Sort",
'''
def mergeSort(seq, start, end):
    if end-start > 1:
        middle = (start+end) / 2
        mergeSort(seq, start, middle)
        mergeSort(seq, middle, end)
        merge(seq, start, middle, middle, end)

def merge(seq, left, leftEnd, right, rightEnd):
    while left<leftEnd and right<rightEnd:
        if seq[left] > seq[right]:
            seq.insert(left, seq.pop(right))
            right += 1
            leftEnd += 1
        else:
            left += 1
            

import random
data = random.sample(range(40), 40)
mergeSort(data, 0, len(data))

# http://en.wikipedia.org/wiki/Merge_sort
''',
'''
barchart(40, 50, 500, 150, data, scale=3)

def segment(index1, index2, name, color):
    w = min(15, 500/len(data))
    x1, x2 = 40 + index1*w, 40 + index2*w
    text(x1-21 if name == 'left' else x2+20, 225, name)
    rect(x1, 210, x2-x1+w, 20, color, color)
    

segment(right, rightEnd, 'right', 'teal')
segment(left, leftEnd, 'left', 'orange')
'''
]

#########################################################################

TUTORIAL_HEAP_SORT = [
"Heap Sort",
'''
from heapq import heappush, heappop

def makeHeap(iterable):
    heap = [] 
    for value in iterable:
        heappush(heap, value)
    return heap
        
numbers = [
   15,25,1,8,7,16,21,2,4,13,6,5,12,22,34,14,18,28,24,20,17
]

# create a heap
heap = makeHeap(numbers)

# use as a priority queue:
result = []
while heap:
    result.append(heappop(heap))
''',
'''
import math

barchart(20, 20, 500, 110, numbers, scale=2)
text(200, 150, 'Unordered List of Tasks')

if heap:
    rect(20, 180, 500, 230)
    text(40, 400, 'heap = %s' % heap)
    text(200, 420, 'Temporary Binary Min-Heap')
    prev_start, prev_count = 0,1
    for level in range(0, 1 + int(math.log(len(heap), 2))):
        y = 220 + level * 35
        start, count = 2**level-1, 2**level
        for n in range(start, start+count):
            x = 20 + (n-start+1) * 500/(count+1)
            p = prev_start + (n-start)/2
            px = 20 + (p-prev_start+1) * 500/(prev_count+1)
            color = 'salmon' if heap[n] == value else 'lightblue' 
            if level > 0: line(x, y, px, y-32, 'orange')
            rect(x-9, y-13, 25, 15, color)
            text(x, y, heap[n])
        prev_start, prev_count = start, count
else:
    barchart(20, 200, 500, 110, result, scale=2)
    text(220, 330, 'Sorted Result')
'''
]

#########################################################################

TUTORIAL_BUZZ_SORT = [
"Binary Search Insertion (Buzz) Sort",
'''
def buzz_sort(L):
    for n,value in enumerate(L):
        index = binary_search(L, value, 0, n - 1)
        if index >= 0 and index != n:
            L.insert(index, L.pop(n))

def binary_search(L, value, min, max):
    while max>=min:
        mid = (min + max) / 2
        if L[mid] < value: min = mid + 1
        elif L[mid] > value: max = mid - 1
        else: return mid
    return min

from random import sample
data = sample(range(30), 30)

buzz_sort(data)

# Insertion sort with n log n behavior by Chris Laffra

# Worst case performance		O(n log n)
# Best case performance			O(n log n)
# Average case performance		O(n log n)
# Worst case space complexity	O(1)
''',
'''
barchart(50, 60, 460, 150, data, highlight=mid, scale=4)

beep(400 + n * 5, 10)

def show(name, index, y, color):
    x = 53+index*460/len(data)
    line(x, y, x, 215, color, 2)
    text(x+3, y+3, '%s = %d' % (name, index), 20)

show('n', n, 250, 'red')
show('min', min, 270, 'teal')
show('mid', mid, 290, 'blue')
show('max', max, 310, 'teal')

rect(35, 330, 490, 40, '#333')
text(80, 360, 'Binary Search Insertion Sort', 30, color='lightblue')
'''
]

#########################################################################

TUTORIAL_BINARY_SEARCH_TREE = [
"Binary Search Tree",
'''
LEFT,VALUE,RIGHT = 0,1,2

def insert(root, node):
    lr = LEFT if node[VALUE] < root[VALUE] else RIGHT
    root[lr] =  insert(root[lr], node) if root[lr] else node
    return root
    
def createTree(data):
    if data:
        tree = [None, data[0], None]
        for v in data[1:]:
        	insert(tree, [None, v, None])
        return tree
        
from random import sample
data = sample(range(0, 100), 30)

# create a non-balanced binary search tree
tree = createTree(data)
''',
'''
def showTree(x, y, px, py, w, node):
    if node:
        if px:
            line(px, py-5, x, y-5, '#AAA', 3)
        l, v, r = node
        showTree(x-w/2-10, y+39, x, y, w/2, l)
        showTree(x+w/2+10, y+39, x, y, w/2, r)
        circle(x, y-5, 10, 'teal')
        text(x-5, y, v, 10, 'Arial', 'white')

text(10, 25, 'Values: %s' % str(data[:20]).replace(']','...]'), 15)
text(10, 50, 'The resulting unbalanced binary search tree:', 15)

showTree(300, 100, 0, 0, 250, tree)

text(30, 410, 'Unbalanced BST', 30, color='orange')
'''
]

#########################################################################

TUTORIAL_AVL_TREE = [
"AVL Tree",
'''
L,V,R,D = 0,1,2,3

def depth(x): return x and x[D] or 0

def insert(x, v):
    edge = L if x[V] > v else R
    x[edge] = insert(x[edge], v) if x[edge] else [None,v,None,1]
    rebalance(x)
    x[D] = 1 + max(depth(x[L]), depth(x[R]))
    return x

def avlTree(data):
    tree = [None, data[0], None, 1]
    for newValue in data[1:]:
        insert(tree, newValue)
    return tree

def rebalance(x):
    ld,rd = depth(x[L]), depth(x[R])
    if abs(ld-rd) > 1:
        l,r = (L,R) if ld>rd else (R,L)
        c = x[l]
        x[V],x[l],x[r],c[l],c[r],c[V] = c[V],c[l],c,c[r],x[r],x[V]
        c[D] = 1 + max(depth(c[l]), depth(c[r]))
        x[D] = 1 + max(depth(x[l]), depth(x[r]))

from random import sample
data = sample(range(0, 100), 30)
tree = avlTree(data)		
''',
'''
def showTree(tx, ty, px, py, w, node):
    if node:
        if px: line(px, py-5, tx, ty-5, '#AAA', 3)
        showTree(tx-w/2-10, ty+40, tx, ty, w/2, node[L])
        showTree(tx+w/2+10, ty+40, tx, ty, w/2, node[R])
        color = 'brown' if node[V]==newValue else 'orange' if node==x else 'teal'
        circle(tx-5, ty-9, 15, color)
        text(tx-15, ty-5, node[V], 17, 'Arial', 'white')

rect(10, 22, 205, 40, '#333')
text(20, 52, 'AVL Tree', 30, color='lightblue')
showTree(300, 100, 0, 0, 250, tree)
text(250, 47, 'Adding: %d' % newValue, 18)
'''
]

#########################################################################

TUTORIAL_PREFIX_TREE = [
"Prefix/Radix/Trie Tree",
'''
from collections import defaultdict

prefixTree = lambda: defaultdict(prefixTree)

def insert(x, k, v):
    if k: insert(x[k[0]], k[1:], v)
    else: x[''] = v

def find(x, k):
    if k[:1] in x:
        return find(x[k[:1]], k[1:]) if k else x[k]
      
data = [ 'tuple', 'in', 'test', 'tuples', 'type', 'tux', 'int' ]

tree = prefixTree()

for word in data:
    insert(tree, word, word.upper())
    
print find(tree, 'tuple'), 
print find(tree, 'missing'), 
print find(tree, 'test')
''',
'''
def showTree(x, y, px, py, node, key=None):
    if px: 
        line(px, py+9, px, y+5, '#AAA', 3)
        line(px, y+5, x, y+5, '#AAA', 3)
    if key:
        rect(x-5, y-10, 35, 35)
        text(x+5, y+15, str(key), 25)
        py = y
    h = 0
    if isinstance(node, str):
        text(x+10, y+10, repr(node), 20, 'Courier', 'blue')
        h = 40
    else:
        for n in sorted(node.keys()):
            h += showTree(x+60, y+h, x+30, py, node[n], n)
    return h

rect(10, 22, 310, 40, '#333')
text(20, 52, 'Prefix/Radix/Trie Tree', 30, color='lightblue')
showTree(20, 100, 0, 55, tree)

for n,c in enumerate(word):
    rect(412+30*n, 28, 25, 25, 'lightyellow')
    text(420+30*n, 47, c, 18)
text(350, 47, 'Add:', 18)
'''
]

#########################################################################

TUTORIAL_TREE_DIAMETER = [
"Tree Diameter",
'''
L,V,R = 0,1,2

def insert(root, node):
    lr = L if root[V] > node[V] else R
    root[lr] = node if not root[lr] else insert(root[lr], node)
    return root

def createTree(data):
    tree = [None, data[0], None]
    for v in data[1:]:
        insert(tree, [None, v, None])
    return tree

def diameter(node, path):
    if node:
        left = diameter(node[L], path)
        right = diameter(node[R], path)
        depth, path = max(left, right)
        return (depth + 1, path + [node[V]])
    return (0,[])

from random import sample
data = sample(range(0, 100), 30)
tree = createTree(data)
width,path = diameter(tree, [])

print 'diameter =', width
print 'longest path =', path
''',
'''
def showTree(x, y, px, py, w, n):
    if n:
        l, v, r = n
        color = 'green' if node==n else 'white'
        try: 
            if v in path: color = 'red'
        except: 
            pass
        if px:
            line(px, py-5, x, y-5, '#AAA', 3)
        showTree(x-w/2-10, y+39, x, y, w/2, l)
        showTree(x+w/2+10, y+39, x, y, w/2, r)
        circle(x, y-5, 15, color)
        text(x-5, y, v, 13, 'Arial')

showTree(300, 50, 0, 0, 230, tree)

text(50, 400, 'Diameter is %d' % width, 20, 'Arial', 'navy')
'''
]

#########################################################################

TUTORIAL_TREE_MERGE = [
"Tree Merge",
'''
L,V,R = 0,1,2

def extract(tree):
    return extract(tree[L]) + [tree[V]] + extract(tree[R]) if tree else []

def insert(root, v):
    lr = L if root[V] > v else R
    root[lr] = insert(root[lr],v) if root[lr] else [None,v,None]
    return root

def tree(data):
    if data:
        mid = len(data)/2
        return [tree(data[:mid]), data[mid], tree(data[mid+1:])]
        
from random import sample
tree1 = tree(sorted(sample(range(0, 100), 10)))
tree2 = tree(sorted(sample(range(0, 100), 10)))

# Rewrite the code below to implement a merge of tree1 + tree2
data = extract(tree1)
result = tree(data)
print data
''',
'''
def show(x, y, tree, width, label):
    def showTree(x, y, px, py, w, treeNode):
        if treeNode:
            if px:
                line(px, py, x, y-5, 'orange', 3)
            l, v, r = treeNode
            showTree(x-w/2-10, y+33, x, y, w/2, l)
            showTree(x+w/2+10, y+33, x, y, w/2, r)
            rect(x-15, y-15, 30, 20, 'lavender')
            text(x-10, y, v)
            
    text(x, y+10, label, 13)
    showTree(x+100+width/2, y+10, 0, 0, width, tree)

show(15, 50, tree1, 100, 'Tree 1:')
show(300, 50, tree2, 100, 'Tree 2:')

line(300,180,300,230,'red',3)
line(290,220,300,230,'red',3)
line(310,220,300,230,'red',3)

show(90, 260, result, 220, 'Result:')
'''
]

#########################################################################

TUTORIAL_DIJKSTRA = [
"Dijkstra's Shortest Path",
'''
import heapq

def dijkstra(graph, start, end):
    queue,seen = [(0, start, [])], set()
    while True:
        (cost, v, path) = heapq.heappop(queue)
        if v not in seen:
            path = path + [v]
            seen.add(v)
            if v == end:
                return cost, path
            for (next, c) in graph[v].iteritems():
                heapq.heappush(queue, (cost + c, next, path))
			
graph = { 
  'a':{'w':14,'x':7,'y':9}, 'b':{'w':9,'z':6}, 'w':{'a':14,'b':9,'y':2},
  'x':{'a':7,'y':10,'z':15}, 'y':{'a':9,'w':2,'x':10,'z':11}, 'z':{'b':6,'x':15,'y':11},
}
print dijkstra(graph,'a','b')
''',
'''
rect(10, 22, 320, 40, '#333')
text(20, 52, 'Dijkstra Shortest Path', 30, color='lightblue')

pos = {'a':(0,100),'x':(150,0),'y':(150,200),'w':(300,0),'z':(300,200),'b':(450,100)}

for v,l in pos.iteritems():
    x1, y1 = l
    for other,w in graph[v].iteritems():
        x2, y2 = pos[other]
        line(80+x1, 150+y1, 80+x2, 150+y2, '#ccc')
        text(80 + x1+(x2-x1)*1/3-10, 150 + y1+(y2-y1)*1/3, w, 15)
        
for v,l in pos.iteritems():
    x, y = l
    color = 'orange' if v in seen else 'lightyellow'
    color = 'pink' if v in path else color
    circle(80+x, 150+y, 30, color)
    text(72+x, 160+y, v, 35)
'''
]

#########################################################################

TUTORIAL_MST = [
"Minimal Spanning Tree",
'''
import heapq

def MST(graph):
    queue = [(0, '#', graph.keys()[0])]
    tree = []
    seen = set()
    while queue:
        _, v0, v1 = heapq.heappop(queue)
        seen.add(v0)
        if v1 not in seen:
            tree.append((v0,v1))
            for (v2, c) in graph[v1].iteritems():
                heapq.heappush(queue, (c, v1, v2))
    return tree
			
graph = {
  'a':{'w':14,'x':7,'y':9},'b':{'w':9,'z':6},'w':{'a':14,'b':9,'y':2},
  'x':{'a':7,'y':10,'z':15},'y':{'a':9,'w':2,'x':10,'z':11},'z':{'b':6,'x':15,'y':11},
} 
print MST(graph)
''',
'''
rect(10, 22, 430, 40, '#333')
text(20, 52, "Prim's Minimum Spanning Tree", 30, color='lightblue')

pos = {
  '#':(0,100),'a':(50,100),'x':(140,0),'y':(160,200),'w':(350,0),'z':(330,200),'b':(450,100)
}

for v in graph.keys():
    x1, y1 = pos[v]
    for other,w in graph[v].iteritems():
        x2, y2 = pos[other]
        line(80+x1, 150+y1, 80+x2, 150+y2, '#ccc')
        text(80 + x1+(x2-x1)/4, 150 + y1+(y2-y1)/4-10, w, 15)

for v,other in tree:
    x1, y1 = pos[v]
    x2, y2 = pos[other]
    line(80+x1, 150+y1, 80+x2, 150+y2, 'red', 5)
        
for v,l in pos.iteritems():
    x, y = l
    color = 'orange' if v in seen else 'lightyellow'
    circle(80+x, 150+y, 15, color)
'''
]

#########################################################################

TUTORIAL_FLOOD_FILL = [
"Flood Fill",
'''
__author__ = "www.google.com/+robertking"

grid = map(list, [
    '......#..#..', '..#...#####.', '..#.........',
    '......#####.', '..##.#.#....', '.#.#..#####.',
])

def flood(grid, i, j):
    if 0 <= i < len(grid) and  0 <= j < len(grid[0]):
        if grid[i][j] == ".":
            grid[i][j] = "*"
            flood(grid, i, j - 1)
            flood(grid, i, j + 1)
            flood(grid, i + 1, j)
            flood(grid, i - 1, j)
    return grid

print grid
print flood(grid, 0, 0)
''',
'''
FILLS = { '*': 'pink', '.': 'white', '#': 'black' }

for y,row in enumerate(grid):
    for x,room in enumerate(row):
        rect(40*x + 35, 40*y + 35, 40, 40, fill=FILLS[room])
        text(40*x + 50, 40*y + 58, room, size=15, font='Arial')
        
text(30, 380, "FLOOD FILL", size=85)
'''
]

#########################################################################

TUTORIAL_BIG_O = [
"Big-O Notation",
'''
import math

def computeBigO(functions, elements):
    operations = [[] for fn in functions]
    for e in elements:
        for n,fn in enumerate(functions):
        	operations[n].append(fn(e))
    return operations

def O_log_n(n): return math.log(n)
def O_n(n): return n
def O_n_log_n(n): return n * math.log(n)
def O_n_2(n): return n * n
def O_2_n(n): return 2 ** n
def O_n_factorial(n): return math.factorial(n)

functions = [ 
    O_log_n, O_n, O_n_log_n, O_n_2, O_2_n, O_n_factorial
]
scores = computeBigO(functions, range(1, 51))
for n,fn in enumerate(functions):
    print '%s\t:\t%s' % (fn, int(scores[n][-1]))
''',
'''
line(50, 50, 50, 400)
line(50, 400, 480, 400)

colors = ['darkgreen','blue','orange','red','purple','black']
o1 = operations[0]
rect(305, 75, 290, 195, 'lightyellow')
text(320, 100, "n", 17)
text(430, 100, len(o1), 17)

for n,fn in enumerate(functions):
    x1,y1 = 50,400
    label = fn.__name__
    for k,value in enumerate(operations[n]):
        if y1>50:
            x2 = 50 + k*9
            y2 = 400 - value/2
            line(x1, y1, x2, y2, colors[n], 3)
            x1,y1 = x2,y2
    text(320, 125 + n*25, label, 17, color=colors[n])
    text(430, 125 + n*25, round(value,2), 17)
    text(x1-31, max(56 + n*15, y1-8), label, 16, color='white')
    text(x1-30, max(55 + n*15, y1-7), label, 15)

rect(0, 0, 600, 50, 'white', 'white')
''' ]

#########################################################################

class TutorialHandler(ShowHandler):
    page = 0

    def get(self):
        self.response.headers.add_header("Content-Type", "text/html")

        user = users.get_current_user()
        if not user:
            template = JINJA_ENVIRONMENT.get_template('login.html')
            login = users.create_login_url('/oscon')
            self.response.write(template.render(locals()))
            return

        def page(title, items):
            self.page += 1
            html = "<div id='page-%d' n='%d' title='%s' class='tutpage'>" % (self.page, self.page, title)
            html += ''.join(items)
            html += "</div>"
            return html

        def algoPage(title, items):
            items = items or ['<br>Coming soon...</br>']
            return page(title, items).replace('tutpage', 'tutpage algopage');

        def progressbar():
            return "<b id=progressbar></b>"

        def arrow(clz, text, url):
            return "<a class='arrow " + clz + "' href=" + url +">" + text + "</a>"

        def h1(value, style=''):
            return "<h1 style='%s'>%s</h1>" % (style, value)

        def block(value):
            return "<div style='width:1280px'>%s</div>" % (value)

        def html(value):
            return value

        def img(src, w=DEMO_WIDTH, h=DEMO_HEIGHT, showLabel=True):
            return "<center><img height=%s width=%s src=%s></center>" % (h,w,src)

        def link(text, url, prefix='', postfix=''):
            return prefix + "<a target=_blank href=" + url +">" + text + "</a>" + postfix

        def algo(name, script, viz):
            params = urllib.urlencode({
                'name': name,
                'share': 'false',
                'script': script[1:-1],
                'viz': viz[1:-1]
            })
            return '<iframe id="algo-%d" class=algo url=show?%s></iframe>' % (self.page + 1, params)

        def absolute(top=0, right=0, bottom=0, left=0, color='black', node=None):
            html = '<div style="position: absolute; ';
            if top: 
                html += 'top:%dpx; ' % top
            if right: 
                html += 'right:%dpx; ' % right
            if bottom: 
                html += 'bottom:%dpx; ' % bottom
            if left: 
                html += 'left:%dpx; ' % left
            html += 'color:%s;' % color
            html += 'text-shadow: -1px 0 black, 0 1px black, 1px 0 black, 0 -1px black;'
            html += '">' + node + '</div>'
            return html

        def relative(top=0, right=0, bottom=0, left=0, color='black', node=None):
            html = '<div style="position: relative; ';
            if top: 
                html += 'top:%dpx; ' % top
            if right: 
                html += 'right:%dpx; ' % right
            if bottom: 
                html += 'bottom:%dpx; ' % bottom
            if left: 
                html += 'left:%dpx; ' % left
            html += 'color:%s;' % color
            html += 'text-shadow: -1px 0 black, 0 1px black, 1px 0 black, 0 -1px black;'
            html += '">' + node + '</div>'
            return html

        def overview(title, highlight=1):
            return page(title, [
                h1("Agenda"),
                html("""
                  <table><tr>
                  <td valign=top width=350 style='background:%s'>
                    <h2>Introduction and Warmup<br>
                    13:30-14:30
                    </h2>
                    <ul>
                        <li>Goals for this Tutorial
                        <li>Introduction
                    </ul>
                    <ul>
                        <li>Algo: FizzBuzz
                        <li>Algo: Knuth Shuffle
                        <li>Algo: Anagram Check
                        <li>Algo: Palindrome Check
                        <li>Algo: Prime Numbers
                        <li>Algo: Permutations
                        <li>Algo: Fibonacci, Golden Ratio
                        <li>Algo: Approximating Pi
                        <li>Algo: Random Pi
                    </ul>
                    <ul>
                        <li>15 Minute Break
                    </ul>
                  </td>
                  <td valign=top width=350 style='background:%s'>
                    <h2>Searching and Sorting<br>
                        14:45-15:45</h3>
                    </h2>
                    <ul>
                        <li>Algo: Linear Search
                        <li>Algo: Binary Search
                        <li>Algo: Breadth First Search
                        <li>Algo: Depth First Search
                    </ul>
                    <ul>
                        <li>Algo: Insertion Sort
                        <li>Algo: Gnome Sort
                        <li>Algo: Quick sort
                        <li>Algo: Merge sort
                        <li>Algo: Heap Sort
                    </ul>
                    <ul>
                        <li>Algo: Buzz Sort
                    </ul>
                    <ul>
                        <li>15 Minute Break
                    </ul>
                  </td>
                  <td valign=top width=350 style='background:%s'>
                    <h2>Graphs and Trees<br>
                        16:00-17:00
                    </h2>
                    <ul>
                        <li>Algo: Binary Search Tree
                        <li>Algo: AVL Tree
                        <li>Algo: Prefix/Radix/Trie
                        <li>Algo: Tree Diameter
                        <li>Algo: Tree merging
                    </ul>
                    <ul>
                        <li>Algo: Dijkstra Shortest Path
                        <li>Algo: Minimum Spanning Tree
                        <li>Algo: Flood Fill
                    </ul>
                    <ul>
                        <li>Conclusions
                        <li>Useful Links
                    </ul>
                  </td></tr></table>
                """ % (
                    'lightyellow' if highlight == 1 else 'white',
                    'lightyellow' if highlight == 2 else 'white',
                    'lightyellow' if highlight == 3 else 'white',
                )),
            ])
            
        oscon = 'http://www.oscon.com/open-source-eu-2015/public/schedule/detail/43642'
        chris = '<a target=_blank style="color:white" href=http://chrislaffra.com>Chris Laffra</a>'

        self.response.write(''.join([
            TUTORIAL_HTML_HEADER,

            html('<div class=header>'),
            arrow("previous", "Previous", "javascript:prevPage()"),
            progressbar(),
            arrow("next", "Next", "javascript:nextPage()"),
            html('</div>'),

            ########################################################################
            page('Algorithms for Fun and Profit', [
                absolute(top=25, node = img('amsterdam.png')),
                relative(top=50,  right=68, color='white', node=h1('Algorithms for Fun and Profit', style='text-align: right')),
                relative(top=100, right=68, color='white', node=h1('<a style="color:white" target=_blank href=' + oscon + '>OSCON Amsterdam</a>', style='text-align: right')),
                relative(top=150, right=68, color='white', node=h1('October 28, 2015', style='text-align: right')),
                relative(top=200, right=68, color='white', node=h1(chris + ', Google NYC', style='text-align: right')),
            ]),
            overview('Overview', 1),
            page('Goals for this Tutorial', [
                block('''
                    <p><br><br>
                    <b>What you will get out of this tutorial:</b>
                    <ul>
                    <li>Deeper understanding of data structures and algorithms
                    <li>Knowledge of complexity of numerous algorithms
                    <li>Increased insight into how visualization helps debugging and explaining
                    </ul>
                    <b>Stretch goals:</b>
                    <ul>
                    <li>Improved coding skills <sup>1</sup>
                    <li>Better preparation for future coding interviews <sup>2</sup>
                    <li>More Money! <sup>3</sup>
                    </ul>
                    <p><br><br>
                    <sup>1</sup> Your mileage may vary. At least you will have fun.<br>
                    <sup>2</sup> Definitely true.<br>
                    <sup>3</sup> OK, maybe not. How about more impact, more fun, or more happiness?<br>
                ''')
            ]),
            page('Introduction', [
                block("""
                    <p>
                    <hr>
                    <p>
                    <b>data structure</b>:
                    A particular way of organizing 
                    data in a computer so that it can be used efficiently.<br>
                    Examples: binary tree, binary search tree, hashtable, heap, stack, queue, graph, list, 
                    tries, ... 
                    <p>
                    <hr>
                    <p>
                    <b>algorithm</b>:
                    A process or set of rules to be followed in calculations or other 
                    problem-solving operations.<br>
                    Examples: insert, delete, search, sort, find shortest path, find max, find min, ...
                    <p>
                    <hr>
                    <br> 
                    <center>
                      <table><tr>
                        <td width=46 align=center valign=middle style="background:#DDD"><h2>4</h2></td> 
                        <td width=46 align=center valign=middle style="background:#CCC"><h2>3</h2></td> 
                        <td width=46 align=center valign=middle style="background:#EEE"><h2>5</h2></td> 
                        <td width=46 align=center valign=middle style="background:#AAA"><h2>1</h2></td> 
                        <td width=46 align=center valign=middle style="background:#BBB"><h2>2</h2></td> 
                      </tr><tr>
                        <td colspan=5 valign=middle align=center style="padding-top: 25px; border-width: 0px"><h2>&darr;</td>
                      </tr><tr>
                        <td colspan=5 valign=middle align=center style="padding-top: 0px; border-width: 0px"><h2>QuickSort</td>
                      </tr><tr>
                        <td colspan=5 valign=middle align=center style="padding-top: 0px; border-width: 0px"><h2>&darr;</td>
                      </tr><tr>
                        <td width=46 align=center valign=middle style="background:#AAA"><h2>1</h2></td> 
                        <td width=46 align=center valign=middle style="background:#BBB"><h2>2</h2></td> 
                        <td width=46 align=center valign=middle style="background:#CCC"><h2>3</h2></td> 
                        <td width=46 align=center valign=middle style="background:#DDD"><h2>4</h2></td> 
                        <td width=46 align=center valign=middle style="background:#EEE"><h2>5</h2></td> 
                      </tr></table>
                """)
            ]),
            page('Often-Quoted Books on Algorithms and Data Structures', [
                html('''
                    <br> <br> <br> <br>
                    <center>
                        <img src=CLRS.jpeg width=275 style="margin:10px; border:2px solid #777">
                        <img src=Skiena.jpg width=275 style="margin:10px; border:2px solid #777">
                        <img src=Wirth.jpg width=275 style="margin:10px; border:2px solid #777">
                        <img src=sedgewick.png width=275 style="margin:10px; border:2px solid #777">
                    </center>
                ''')
            ]),
            page('P vs. NP - Definition', [
                html('''
                <br>
                <table width=900 border=5 cellpadding=100><tr><td>
                    <br><br>
                    <h1 style='text-align: left'>Complexity</h1>
                    <br><br>
                    <h1 style='text-align: left'>
                    P = Solution can be verified in polynomial time, e.g., n<sup>2</sup>
                    <br> <br>
                    NP = Non-Deterministic Polynomial, e.g., 2<sup>n</sup>
                    <br><br>
                    P == NP: If a solution can be quickly <u>verified</u>, it can be quickly <u>solved</u>.
                    </h1>
                </td></tr></table>
                <br><br>
                <a href=https://en.wikipedia.org/wiki/P_versus_NP_problem target=_blank> Wikipedia </a>
                ''')
            ]),
            algoPage('Complexity and Big-O Notation', [
                algo(*TUTORIAL_BIG_O),
            ]),
            algoPage('Demo: BubbleSort', [
                algo(*TUTORIAL_BUBBLESORT),
            ]),
            page("PyAlgoViz Architecture", [
                img(DEMO_SLIDES + "slide-4-1024.jpg"),  # Pycon poster - browser
            ]),
            page("The Architecture of PyAlgoViz - server-side", [
                img(DEMO_SLIDES + "slide-5-1024.jpg"),  # Pycon poster - server
            ]),
            page("The Architecture of PyAlgoViz - runtime", [
                img(DEMO_SLIDES + "slide-6-1024.jpg"),  # pseudo code for pyalgoviz
            ]),
            page('How to learn algorithms', [
                block('''
                <br><br><br>
                <b>Things to remember</b>:
                <ul>
                <li>Don't memorize the code for a given algorithm.
                <p>
                <li>Focus on understanding how and why an algorithm works.
                <p>
                <li>Understand the motivation behind the problem.
                <p>
                <li>How does it solve real-world problems? 
                <p>
                <li>What are the special insights used by the algorithm?
                <p>
                <li>Know the limitations of a given algorithm and how to improve it.
                <p>
                <li>Algorithms are space-time trade-offs.
                ''')
            ]),
            algoPage('Algo: FizzBuzz', [
                algo(*TUTORIAL_FIZZBUZZ),
            ]),
            algoPage('Algo: Knuth Shuffle', [
                algo(*TUTORIAL_KNUTH_SHUFFLE),
            ]),
            algoPage('Algo: Anagram Check', [
                algo(*TUTORIAL_ANAGRAM_CHECK),
            ]),
            algoPage('Algo: Palindrome Check', [
                algo(*TUTORIAL_PALINDROME_CHECK),
            ]),
            algoPage('Algo: Prime Numbers', [
                algo(*TUTORIAL_PRIME_NUMBERS),
            ]),
            algoPage('Algo: Permutations', [
                algo(*TUTORIAL_PERMUTATIONS),
            ]),
            algoPage('Algo: Fibonacci, Golden Ratio', [
                algo(*TUTORIAL_FIBONACCI),
            ]),
            algoPage('Algo: Approximating Pi', [
                algo(*TUTORIAL_PI),
            ]),
            algoPage('Algo: Random Pi', [
                algo(*TUTORIAL_RANDOM_PI),
            ]),

            page('15 Minute Break until 14:45 ', [
                block(CLOCK % ('clock1', 'clock1'))
            ]),

            ########################################################################
            overview('Section 2', 2),
            algoPage('Algo: Linear Search', [
                algo(*TUTORIAL_LINEAR_SEARCH),
            ]),
            algoPage('Algo: Binary Search', [
                algo(*TUTORIAL_BINARY_SEARCH),
            ]),
            algoPage('Algo: Breadth First Search', [
                algo(*TUTORIAL_BFS),
            ]),
            algoPage('Algo: Depth First Search', [
                algo(*TUTORIAL_DFS),
            ]),

            algoPage('Algo: Gnome Sort', [
                algo(*TUTORIAL_GNOME_SORT),
            ]),
            algoPage('Algo: Insertion Sort', [
                algo(*TUTORIAL_INSERTION_SORT),
            ]),
            algoPage('Algo: Quick sort', [
                algo(*TUTORIAL_QUICK_SORT),
            ]),
            algoPage('Algo: Merge sort', [
                algo(*TUTORIAL_MERGE_SORT),
            ]),
            algoPage('Algo: Heap Sort', [
                algo(*TUTORIAL_HEAP_SORT),
            ]),
            algoPage('Algo: Buzz Sort', [
                algo(*TUTORIAL_BUZZ_SORT),
            ]),

            page('15 Minute Break until 16:00', [
                block(CLOCK % ('clock2', 'clock2'))
            ]),

            ########################################################################
            overview('Section 3', 3),
            algoPage('Algo: Binary Search Tree', [
                algo(*TUTORIAL_BINARY_SEARCH_TREE),
            ]),
            algoPage('Algo: AVL Tree', [
                algo(*TUTORIAL_AVL_TREE),
            ]),
            algoPage('Algo: Prefix/Radix/Trie', [
                algo(*TUTORIAL_PREFIX_TREE),
            ]),
            algoPage('Algo: Tree Diameter', [
                algo(*TUTORIAL_TREE_DIAMETER),
            ]),
            algoPage('Algo: Tree merging', [
                algo(*TUTORIAL_TREE_MERGE),
            ]),
            algoPage('Algo: Dijkstra Shortest Path', [
                algo(*TUTORIAL_DIJKSTRA),
            ]),
            algoPage('Algo: Minimum Spanning Tree', [
                algo(*TUTORIAL_MST),
            ]),
            algoPage('Algo: Flood Fill', [
                algo(*TUTORIAL_FLOOD_FILL),
            ]),

            overview('Conclusions', 0),

            page('Links', [
                html('<br><br><b>Useful Links</b>:<ul>'),
                link(
                    'chrislaffra.com', 
                    'https://chrislaffra.com',
                    '<li style="margin-bottom:20px">', '</li>'
                ),
                link(
                    'Video on P vs. NP', 
                    'https://www.youtube.com/watch?v=YX40hbAHx3s',
                    '<li style="margin-bottom:20px">', '</li>'
                ),
                link(
                    'The Algorithm Design Manual', 
                    'http://www.algorist.com/',
                    '<li style="margin-bottom:20px">', '</li>'
                ),
                link(
                    'Introduction to Algorithms', 
                    'http://www.amazon.com/Thomas-H.-Cormen/e/B000AQ24AS/ref=dp_byline_cont_book_1',
                    '<li style="margin-bottom:20px">', '</li>'
                ),
                link(
                    'Huge and authoritative list of algorithms', 
                    'http://www.geeksforgeeks.org/fundamentals-of-algorithms/',
                    '<li style="margin-bottom:20px">', '</li>'
                ),
                link(
                    'Insightful Quora Answer on Interviewing', 
                    'http://www.quora.com/Marcelo-Juchem',
                    '<li style="margin-bottom:20px">', '</li>'
                ),
                link(
                    'Steve Yegge: Get that job at Google', 
                    'http://steve-yegge.blogspot.com/2008/03/get-that-job-at-google.html',
                    '<li style="margin-bottom:20px">', '</li>'
                ),
                link(
                    'Send your resume to Chris Laffra', 
                    'mailto:laffra@gmail.com?Subject=Here%20is%20my%20resume',
                    '<li style="margin-bottom:20px">', '</li>'
                ),
                html('</ul>'),
            ]),

            TUTORIAL_SCRIPT,
            JINJA_ENVIRONMENT.get_template('all.html').render({
                'editor_width':800, 
                'name': self.request.get('name'),
                'editor_height':800,
                'jstabs': False,
            }) + "</div></body></html>"
        ]))


CLOCK = '''
<center>
    <br><br><br><br><br>
    <canvas id="%s" width="400" height="400"></canvas>
    <!-- See: http://www.encodedna.com/html5/canvas/simple-analog-clock-using-canvas-javascript.htm -->
</center>
<script>
setInterval(showClock, 1000);function showClock() {var canvas=document.getElementById('%s');var ctx=canvas.getContext('2d');var date=new Date;var angle;var secHandLength=160;ctx.clearRect(0,0,canvas.width,canvas.height);OUTER_DIAL1();OUTER_DIAL2();CENTER_DIAL();MARK_THE_HOURS();MARK_THE_SECONDS();SHOW_SECONDS();SHOW_MINUTES();SHOW_HOURS();function OUTER_DIAL1() {ctx.beginPath();ctx.arc(canvas.width/2,canvas.height/2,secHandLength+10,0,Math.PI*2);ctx.strokeStyle='#92949C';ctx.stroke();}function OUTER_DIAL2() {ctx.beginPath();ctx.arc(canvas.width / 2, canvas.height / 2, secHandLength + 7, 0, Math.PI * 2);ctx.strokeStyle = '#929BAC';ctx.stroke();}function CENTER_DIAL() {ctx.beginPath();ctx.arc(canvas.width/2,canvas.height/2,2,0,Math.PI*2);ctx.lineWidth=3;ctx.fillStyle='#353535';ctx.strokeStyle='#0C3D4A';ctx.stroke();}function MARK_THE_HOURS() {for (var i=0;i<12;i++) {angle=(i-3)*(Math.PI*2)/12;ctx.lineWidth=1;ctx.beginPath();var x1=(canvas.width/2)+Math.cos(angle)*(secHandLength);var y1=(canvas.height/2)+Math.sin(angle)*(secHandLength);var x2=(canvas.width/2)+Math.cos(angle)*(secHandLength-(secHandLength/7));var y2=(canvas.height/2)+Math.sin(angle)*(secHandLength-(secHandLength/7));ctx.moveTo(x1, y1);ctx.lineTo(x2, y2);ctx.strokeStyle='#466B76';ctx.stroke();}}function MARK_THE_SECONDS() {for (var i=0;i<60;i++) {angle=(i-3)*(Math.PI*2)/60;ctx.lineWidth=1;ctx.beginPath();var x1=(canvas.width/2)+Math.cos(angle)*(secHandLength);var y1=(canvas.height/2)+Math.sin(angle)*(secHandLength);var x2=(canvas.width/2)+Math.cos(angle)*(secHandLength-(secHandLength/30));var y2=(canvas.height/2) + Math.sin(angle)*(secHandLength-(secHandLength/30));ctx.moveTo(x1, y1);ctx.lineTo(x2, y2);ctx.strokeStyle='#C4D1D5';ctx.stroke();}}function SHOW_SECONDS() {var sec=date.getSeconds();angle=((Math.PI*2)*(sec/60))-((Math.PI*2)/4);ctx.lineWidth=0.5;ctx.beginPath();ctx.moveTo(canvas.width/2,canvas.height/2);ctx.lineTo((canvas.width/2+Math.cos(angle)*secHandLength),canvas.height/2+Math.sin(angle)*secHandLength);ctx.moveTo(canvas.width/2,canvas.height/2);ctx.lineTo((canvas.width/2-Math.cos(angle)*20),canvas.height/2-Math.sin(angle)*20);ctx.strokeStyle='#586A73';ctx.stroke();}function SHOW_MINUTES() {var min=date.getMinutes();angle=((Math.PI*2)*(min/60))-((Math.PI*2)/4);ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(canvas.width/2,canvas.height/2);ctx.lineTo((canvas.width/2+Math.cos(angle)*secHandLength/1.1),canvas.height/2+Math.sin(angle)*secHandLength/1.1);ctx.strokeStyle='#999';ctx.stroke();}function SHOW_HOURS() {var hour=date.getHours();var min=date.getMinutes();angle=((Math.PI*2)*((hour*5+(min/60)*5)/60))-((Math.PI*2)/4);ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(canvas.width/2,canvas.height/2);ctx.lineTo((canvas.width/2+Math.cos(angle)*secHandLength/1.5),canvas.height/2+Math.sin(angle)*secHandLength/1.5);ctx.strokeStyle='#000';ctx.stroke();}}
</script>
'''

class ShareHandler(webapp2.RequestHandler):
    def get(self):
        author = users.get_current_user()
        name = self.request.get('name')
        query = Algorithm.query(ancestor=ndb.Key('Python Algorithms', 'scrap')) \
            .filter(Algorithm.author == author) \
            .filter(Algorithm.name == name) \
            .order(Algorithm.date)
        self.response.content_type = 'application/json'
        try:
            for algo in query.fetch(None):
                algo.public = True
                algo.put()
            msg = 'User %s shared "%s".' % (author.email(), name)

            result = Executor(algo.script, algo.viz, False)
            if result.events:
                step = max(1,len(result.events)/10)
                events = result.events[2::step] + [result.events[-1]]
                algo.events = str([viz for _,viz,_ in events])
                algo.put()
                msg += '\nAdded %d preview events' % len(events)
            else:
                msg += '\nNo preview events were recorded'
            info(msg)
            notify(author, 'share', algo.name, algo.script, algo.viz)
            self.response.write(json.encode({ 'result': msg }))
        except Exception as e:
            msg = 'Cannot share "%s": %s' % (
                name,e)
            error(msg)
            self.response.write(json.encode({ 'result': msg }))


class DeleteHandler(webapp2.RequestHandler):
    def get(self):
        author = users.get_current_user()
        name = self.request.get('name')
        query = Algorithm.query(ancestor=ndb.Key('Python Algorithms', 'scrap')) \
            .filter(Algorithm.author == author) \
            .filter(Algorithm.name == name)
        self.response.content_type = 'application/json'
        try:
            for version in query.fetch(None):
                version.key.delete()
            self.response.write(json.encode({ 'result': 'Deleted "%s"' % name }))
            info('User %s deleted "%s"' % (
                author.email(), 
                self.request.get('name'), 
            ))
        except Exception as e:
            self.response.write(json.encode({ 'result': 'Could not delete "%s": %s' % (name,e) }))


vizOutput = ''


def number(x, y, label, value, scale=4, color='black'):
    text(x, y+10, label)
    rect(x+20, y, value*scale, 10, color)
    text(x+22+value*scale, y+10, value)

def barchart(x, y, w, h, items, highlight=-1, scale=1, fill='black', border='black'):
    rect(x, y, w, h, '#FDFDF0', border)
    if items:
        d = min(15, int(w/len(items)))
        offset = (w - len(items)*d)/2
        for n,item in enumerate(items):
            hitem = item*scale
            rect(offset+x+n*d, y+h-hitem, d-2, hitem, 'red' if n==highlight else fill)

NUMBER = ('number', (int,float))
STRING = ('string', str)

def check(primitive, param, value, expected):
    kind,typ = expected
    assert isinstance(value, typ), 'expected a %s for %s.%s, instead got %s' % (
        kind, primitive, param, repr(value)
    )

def beep(frequency, duration):
    check('beep', 'frequency', frequency, NUMBER)
    check('beep', 'duration', duration, NUMBER)
    global vizOutput
    vizOutput += 'B(%s,%s);' % (frequency, duration)

def text(x, y, txt, size=13, font='Arial', color='black'):
    check('text', 'x', x, NUMBER)
    check('text', 'y', x, NUMBER)
    check('text', 'size', size, NUMBER)
    check('text', 'font', font, STRING)
    check('text', 'color', color, STRING)
    global vizOutput
    vizOutput += 'T(%d,%d,%r,%d,%r,%r);' % (x, y, str(txt), size, font, color)

def line(x1, y1, x2, y2, color='black', width=1):
    global vizOutput
    vizOutput += 'L(%s,%s,%s,%s,%r,%s);' % (x1, y1, x2, y2, color, width)

def rect(x, y, w, h, fill='white', border='black'):
    check('rect', 'x', x, NUMBER)
    check('rect', 'y', x, NUMBER)
    check('rect', 'w', w, NUMBER)
    check('rect', 'h', h, NUMBER)
    check('rect', 'fill', fill, STRING)
    check('rect', 'border', border, STRING)
    global vizOutput
    vizOutput += 'R(%s,%s,%s,%s,%r,%r);' % (x, y, w, h, fill, border)

def circle(x, y, radius, fill='white', border='black'):
    check('circle', 'x', x, NUMBER)
    check('circle', 'y', x, NUMBER)
    check('circle', 'radius', radius, NUMBER)
    check('circle', 'fill', fill, STRING)
    check('circle', 'border', border, STRING)
    global vizOutput
    vizOutput += 'C(%s,%s,%s,%r,%r);' % (x, y, radius, fill, border)

def arc(cx, cy, innerRadius, outerRadius, startAngle, endAngle, color='black'):
    check('circle', 'cx', cx, NUMBER)
    check('circle', 'cy', cx, NUMBER)
    check('circle', 'innerRadius', innerRadius, NUMBER)
    check('circle', 'outerRadius', outerRadius, NUMBER)
    check('circle', 'startAngle', startAngle, NUMBER)
    check('circle', 'endAngle', endAngle, NUMBER)
    check('circle', 'color', color, STRING)
    global vizOutput
    vizOutput += 'A(%s,%s,%s,%s,%s,%s,%r);' % (
        cx, cy, innerRadius, outerRadius, startAngle, endAngle, color
    )


class Executor(object):
    def __init__(self, script, viz, showVizErrors):
        self.error = dict(msg='',lineno=0)
        self.events = []
        self.state = []
        self.lastLine = -1
        self.viz = viz
        self.showVizErrors = showVizErrors
        self.vars = {}
        self.vizPrims = { 
            'text':text,
            'number':number,
            'barchart':barchart,
            'line':line,
            'rect':rect,
            'beep':beep,
            'circle':circle,
            'arc':arc,
            'vizOutput':vizOutput,
        }
        sandbox = Sandbox(script)
        try:
            sys.exc_clear()
            with sandbox:
                with self:
                    exec script in self.vars
                    self.createEvent(self.lastLine)
            lastViz = self.events[-1][1]
            msg = '\nProgram finished.\n\nHit F9 or Ctrl-Enter to run the script again.'
            self.events.append((self.lastLine, lastViz, msg))
        except Exception as e:
            tb = sys.exc_info()[2]
            stack = traceback.extract_tb(tb)
            lines = [0]+[lineno for filename,lineno,fn,txt in stack if filename == '<string>']
            msg = '=' * 70
            msg += '\nError at line %d: %s\n' % (lines[-1], ERROR or e)
            msg += '-' * 70
            msg += '\n%s\n' % '\n'.join(['%s = %r' % v for v in self.state])
            msg += '=' * 70
            self.error = dict(msg=msg, lineno=lines[-1])
        if '__builtins__' in self.vars:
            del self.vars['__builtins__']
    
    def __enter__(self):
        self.start = time.time()
        self.stdout, self.stderr = sys.stdout, sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        sys.settrace(self.trace)

    def getVars(self, frame):
        return [(k,v) for k,v in sorted(frame.f_locals.iteritems()) if '__' not in k]

    def trace(self, frame, event, args):
        now = time.time()
        if now - self.start > 10:
            self.events = self.events[-100:]
            raise TimeoutError('\nScript ran for more than 10 seconds and has been canceled.' + 
                               '\n\nShowing just the last 100 events.')
        if frame.f_code.co_filename == '<string>' and self.lastLine != frame.f_lineno:
            state = self.getVars(frame)
            if event != 'exception':
                self.state = state
            global vizOutput
            vizOutput = ''
            for k,v in state:
                self.vizPrims[k] = v
            self.vizPrims['__lineno__'] = frame.f_lineno
            try:
                exec self.viz in self.vizPrims
            except Exception as e:
                if self.showVizErrors:
                    tb = traceback.extract_tb(sys.exc_info()[2])
                    lines = [0]+[lineno for filename,lineno,fn,txt in tb if filename == '<string>']
                    print 'line %d: %s' % (lines[-1], e)
            self.createEvent(frame.f_lineno)
            self.lastLine = frame.f_lineno
            return self.trace

    def createEvent(self, lineno):
        output = sys.stdout.getvalue()
        self.events.append((lineno, vizOutput, output))
        sys.stdout.truncate(0)

    def __exit__(self, *args):
        sys.settrace(None)
        self.output = sys.stdout.getvalue()
        sys.stdout, sys.stderr = self.stdout, self.stderr


NOT_IMPLEMENTED = [ 
    '__import__', 'delattr', 'exit', 'type', 
    'intern', 'reload', 'file', 'eval', 'dir', 'vars',
    'compile', 'execfile', 'globals', 'locals',
]
OK_IMPORTS = [
   're',  'math', 'random', 'decimal', 'heapq', 'time', 'main',
   'collections', 'func', 'itertools', 'struct', 'fractions',
]
BAD = [ 
    '__base__', '__class__', '__subclasses__', '__getattr__', '__setattr__',
    '__globals__', '__locals__', '__name__', '__builtins__',
    '__getattribute__', '__get__', '__dict__', '__builtin__',
]

IMPORT = __import__

def __import__(name, globals=None, locals=None, fromlist=None, level=-1):
    if name:
        if name in OK_IMPORTS:
            return IMPORT(name, globals, locals, fromlist, level)
        ERROR = 'Import Error: module "%s" is not supported.' % name
        print ERROR
        raise NotImplementedError(ERROR)

ORIGINAL = { "__import__": IMPORT }
ERROR = ""
SCRIPT = ""


class StaticChecker(ast.NodeVisitor):
    def visit_Attribute(self, node):
        checkBad(node.attr)

    def visit_Name(self, node):
        checkBad(node.id)

GETATTR = getattr

def checkBad(name):
    if name in BAD:
        ERROR = 'Unsupported feature: ' + name
        raise NotImplementedError(ERROR)
         
def builtin_getattr(obj, name, default=None):
    checkBad(name)
    return GETATTR(obj, name, default)
        

def notimplemented(name, *args, **kwargs): 
    if name != 'type':
        ERROR = '"%s" is an unsupported feature' % name.replace('_','')
        print ERROR
        raise NotImplementedError(ERROR)


class Sandbox():
    def __init__(self, script):
        global SCRIPT
        SCRIPT = script
        ERROR = ""
        
    def __enter__(self):
        ERROR = ''
        __builtin__.getattr = builtin_getattr
        StaticChecker().visit(ast.parse(SCRIPT))
        for name in NOT_IMPLEMENTED:
            ORIGINAL[name] = getattr(__builtin__, name)
            replacement = __import__ if name == "__import__" else partial(notimplemented, name)
            setattr(__builtin__, name, replacement)

    def __exit__(self, *args):
        __builtin__.getattr = GETATTR
        for name in NOT_IMPLEMENTED:
            setattr(__builtin__, name, ORIGINAL[name])


class TimeoutError(Exception): 
    pass
 

class NotImplementedError(Exception): 
    def __init__(self, msg):
        info(msg)
        Exception.__init__(self, msg)

application = webapp2.WSGIApplication([
    ('/',       MainHandler),
    ('/user',   UserHandler),
    ('/log',    LogHandler),
    ('/source', SourceHandler),
    ('/update', UpdateHandler),
    ('/users',  UsersHandler),
    ('/show',   ShowHandler),
    ('/link',   LinkHandler),
    ('/run',    RunHandler),
    ('/demo',   DemoHandler),
    ('/oscon',  TutorialHandler),
    ('/oscon-dashboard', TutorialDashboardHandler),
    ('/save',   SaveHandler),
    ('/close',  CloseHandler),
    ('/load',   LoadHandler),
    ('/delete', DeleteHandler),
    ('/share',  ShareHandler),
], debug=True)


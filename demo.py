import os
import cgi
import ast
import sys
import time
import types
import jinja2
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
from models import Comment
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
        name = self.request.get('name')
        user = users.get_current_user()
        if user:
            logout = users.create_logout_url("/")
            script = viz = ''
            if name:
                _, script, viz, author = self.loadScript(name, user)
            else:
                script = viz = ""
                author = user
            editor_width = 1150 if tabs else 600
            editor_height = 640 if tabs else 450
            jstabs = "true" if tabs else "false"
            template = JINJA_ENVIRONMENT.get_template('edit_tabs.html' if tabs else 'edit.html')
            html = template.render(locals())
            self.response.write(html)
            self.response.headers.add_header("Content-Type", "text/html")
            logging.info('Response: %d bytes' % len(html))
        else:
            template = JINJA_ENVIRONMENT.get_template('login.html')
            next = '/show?edit=%s&name=%s' % (edit, name)
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
        author = users.get_current_user()
        if author:
            result = Executor(
                self.request.get('script'), 
                self.request.get('viz'), 
                self.request.get('showVizErrors') == 'true',
            )
            info('User %s ran "%s":\n%s' % (
                author.email(), 
                self.request.get('name'), 
                self.request.get('script'), 
            ))
            self.response.content_type = 'application/json'
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
            return "<div>%s</div>" % (value)

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

        def link(text, url):
            return "<a target=_blank href=" + url +">" + text + "</a>"

        def algo(name):
            id = name.replace(' ', '%20')
            return "<a name=" + id +"></a><div id='" + id + "' class=demo_outer><div class=demo>" + \
                "<p><button name=" + id + " onclick='demo(this.name)' " + \
                "tabs=true>Load \"" + name +"\"</button> " + \
                "</div></div><p>"

        self.response.write(''.join([
            DEMO_HTML_HEADER,
            
            img(DEMO_SLIDES + "slide-1-1024.jpg", showLabel=False),  # title slide
            html("<center><div class=dedication>This talk is dedicated to <b>Daphne Tammer</b>, " + \
                "bravely fighting Leukemia with a never-ending smile, " + \
                "being an inspiration to us all.</div></center><br><br>"),

            html("<center><h1>Watch the <a href=https://plus.google.com/104991931781045204476/posts/dbDLHhEcBCw target=_blank>video</a> for this presentation</h1></center>"),
            
            img("http://i.imgur.com/Pm0T2iv.jpg", 1000, 1000),  # Insanity Wolf

            img(DEMO_SLIDES + "slide-2-1024.jpg"),  # three pillars of excellence
            
            img(DEMO_SLIDES + "slide-3-1024.jpg"),  # Pycon poster

            h1("My Approach - An AppEngine Site with Algorithm Visualizations"),
            html(
                "<ul>" + \
                "<li>Develop <a target=_blank href=http://pyalgoviz.appspot.com>PyAlgoViz</a>" + \
                "<li>Publicize at Google Plus and Facebook" + \
                "<li>Present at local Python meetups" + \
                "<li>Submit to Pycon" + \
                "<li>Make a T-Shirt" + \
                "<li>Demonstrate during interviews" + \
                "</ul><p>"
            ),
            algo("How I Got My Job"),

            h1("Let's Start with Bubble Sort"),
            algo("Xtra - Demos - BubbleSort"),

            h1("Python Algorithm Visualization Primitives"),
            html(DEMO_HELP),

            joke('"Knock, knock."\n\n"Who\'s there?"\n\nvery long pause...\n\n"Java."'),

            h1("Pi by Archimedes - 2,300 years ago"),
            algo("Geometry - Pi Archimedes"),
            h1("Pi by the Chudnovsky Brothers"),
            algo("Geometry - Pi Chudnovsky"),

            joke("Why doesn't C++ have a garbage collector?\n\nBecause there would be nothing left!"),
            
            h1("Pi Using Probability Theory"),
            algo("Geometry - Pi Buffon"),

            h1("Anyone Can Contribute an Algorithm"),
            algo("Boyer-Moore-Horspool"),

            joke("<img width=700 src=http://upload.wikimedia.org/wikipedia/commons/7/74/The_Long_Road_Ahead.jpg>"),

            h1("The Mystery Polygon"),
            algo("Polygon Area"),

            joke("<a target=_blank href=http://www.google.com/#q=recursion>Google recursion</a>"),

            h1("Shannon Entropy"),
            algo("ShannonEntropy"),

            joke("<img width=700 src=http://imgs.xkcd.com/comics/random_number.png><br>XKCD 221"),

            h1("Marketing Yourself"),
            img("https://lh5.googleusercontent.com/-9duKVov_t7w/UnQR1JadWWI/AAAAAAAAFFA/4Oc1YRP9Hl8/w1120-h563-no/GreatBooks.png"),
            img("http://i.imgur.com/n8J9xtW.jpg"),
            img("http://i.imgur.com/L8bjov7.jpg"),

            h1("Numbers"),
            algo("Numbers - Fibonnacci Generator"),
            label(False),
            algo("Numbers - Fibonacci / Golden Ratio"),

            joke('Q: "What is the object-oriented way to become wealthy?"\n\nA: Inheritance'),

            algo("Numbers - Mandelbrot Set"),
            label(False),
            algo("Numbers - Prime Generator"),

            h1("Patterns Are Ubiquitous"),
            algo("FizzBuzz"),

            joke("<center><img width=400 src=http://imgur.com/eNxPtlK.jpg></center>"),
            
            h1("Various Sorting Algorithms Compared"),
            algo("Sorting - Comb Sort"),
            label(False),
            algo("Sorting - Cocktail Sort"),
            label(False),
            algo("Sorting - Gnome Sort"),

            joke("Some people, when confronted with a problem, think \n"+ \
                 "\"I know, I'll use regular expressions.\" \n\n" + \
                 "Now they have two problems.\n\n<i>Jamie Zawinski</i>"),

            h1("Hotwire Debugger - Usenix - 1994"),
            img("http://i.imgur.com/bDBUuIN.png"),    # Hotwire 
            img("http://i.imgur.com/xngZeAL.png"),    # Hotwire 

            h1("Eclipse - XRay - 2004"),
            img("http://i.imgur.com/E6B9mv9.jpg", 802, 938),    # Eclipse XRay

            algo("Sorting - Insertion Sort"),
            label(False),
            algo("Sorting - BuzzSort"),
            label(False),
            algo("Sorting - MergeSort"),
            label(False),
            algo("Sorting - Heap Sort"),

            joke("There are 10 types of people.\nThose who get binary jokes and those who don't."),

            h1("The Evolution of QuickSort"),
            algo("Sorting - QuickSort"),
            label(False),
            algo("Sorting - QuickSort Sedgewick"),

            joke("To understand what recursion is, you must first understand recursion."),

            algo("Sorting - QuickSort Stackless"),

            img(DEMO_SLIDES + "slide-4-1024.jpg"),  # Pycon poster - browser
            img(DEMO_SLIDES + "slide-5-1024.jpg"),  # Pycon poster - server
            img(DEMO_SLIDES + "slide-6-1024.jpg"),  # pseudo code for pyalgoviz
            img("https://lh5.googleusercontent.com/-fMrbv5WseXs/U12wIrhTXaI/AAAAAAAAHpU/o1cCRk1HwzM/w433-h273/python+sandboxing.gif"),  # sandbox meme

            h1("Graphs"),
            algo("Graphs - Dijkstra Shortest Path"),
            label(False),
            algo("Computational Geometry - Convex Hulls"),
            label(False),
            algo("Graphs - MST"),

            img("http://i.imgur.com/Jmo86Kc.jpg"),  # going viral
            h1("Webdriver Torso - Aqua"),
            html("80,000 videos of 11s each with random blue/red rectangles and beeps"+"<br>"*2),
            link("BBC Article"+"<br>"*2, "http://www.bbc.com/news/technology-27238332"),
            link("Youtube Sample"+"<br>"*2, "https://www.youtube.com/watch?v=-w3c2j6jO5s"),
            algo("Webdriver Torso - Aqua"),
            img("http://i.imgur.com/0hIpnua.jpg"),

            h1("Trees"),
            algo("Searching - BFS"),
            label(False),
            algo("Searching - DFS"),
            label(False),
            algo("Searching - DFS - Non-Recursive"),
            label(False),
            algo("Sorting - TreeSort"),
            label(False),
            algo("Trees - AVL"),

            joke("<img width=700 src=http://i.imgur.com/PdMQ5.gif>"),

            h1("Some Inspiration and Further Readings"),
            persons([
                ("Bret Victor", "i.imgur.com/JnBubty.png", "worrydream.com/#", 300, 200),
                ("LightTable",  "i.imgur.com/zALM8io.png", "lighttable.com", 300, 200),
                ("Code Golf", "www.python.org/static/community_logos/python-powered-h-100x130.png",
                        "codegolf.stackexchange.com/questions/54/tips-for-golfing-in-python", 
                        200, 200),
                ("AppInventor", "i.imgur.com/c0IlZh8.png", "appinventor.mit.edu", 200, 200),
                ("Python Tutor", "i.imgur.com/uXX9hf3.png", "pythontutor.com/", 350, 200),
                ("IP[y]",  "nbviewer.ipython.org/static/img/example-nb/ipython-thumb.png", 
                            "nbviewer.ipython.org/", 300, 200),
            ]),

            h1("Conclusions"),
            img(DEMO_SLIDES + "slide-8-1024.jpg"),  # summary - three pillars
            img(DEMO_SLIDES + "slide-9-1024.jpg"),  # Q&A
            "<br>" * 13,

            DEMO_SCRIPT,
            DEMO_HTML_FOOTER
        ]))


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
                events = [viz for lineno,viz,output in events]
                algo.events = str(events)
                algo.put()
                msg += '\nAdded %d preview events' % len(events)
            else:
                msg += '\nNo preview events were recorded'
            info(msg)
            notify(author, 'share', algo.name, algo.script, algo.viz)
            self.response.write(json.encode({ 'result': msg }))
        except Exception as e:
            msg = 'Cannot publish "%s": %s' % (name,e)
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
        sys.stdout = sys.stderr = StringIO()
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
    ('/save',   SaveHandler),
    ('/delete', DeleteHandler),
    ('/share',  ShareHandler),
], debug=True)



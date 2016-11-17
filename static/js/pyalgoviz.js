
var events = [];
var currentEvent = 0;
var lastEvent = -1;
var lastError = ''
var dirty = false
var nameChanged = false
var showVizErrors = false
var OUTPUT = ''

function initAudio() {
    var audio = new webkitAudioContext();
    var gain = audio.createGain(); 
    gain.gain.value = 0; 
    var osc = audio.createOscillator()
    osc.type = 0;
    osc.frequency.value = 0;
    osc.start(0)
    osc.connect(gain);
    gain.connect(audio.destination);
}

function B(freq, duration) {
    try {
        if (document.location.href.indexOf('show?') != -1) {
            duration = duration/1000
            var now = audio.currentTime;
            osc.frequency.value = freq;
            gain.gain.cancelScheduledValues( now );
            gain.gain.setValueAtTime(gain.gain.value, now);
            gain.gain.linearRampToValueAtTime(0.05, now + duration/4)
            gain.gain.linearRampToValueAtTime(0.0, now + duration)
        }
    } catch(e) {
        OUTPUT = 'This browser does not support audio\n'
    }
}

function doRunScript() {
    outputArea.setValue('Running...');
    $('*').css('cursor','wait');
    $("#runButton").attr("disabled", "disabled");
    $('#stopButton span').html('Stop');        
    params = { 
        name: $('#name').val(), 
        script: scriptEditor.getValue(), 
        viz: vizEditor.getValue(),
        showVizErrors: showVizErrors
    }
    d3.json("/run", function(data) {
        $('*').css('cursor','auto');
        $("#runButton").removeAttr("disabled");
        error = data['error'];
        events = data['events'];
        outputArea.setValue(error.msg);
        $('#slider').slider({
            value: 1,
            step: 1,
            min: 0,
            max: events.length-1,
            slide: function( event, ui ) { currentEvent=ui.value; showEvent() }
        });
        lastError = ''
        if (error.lineno > 0) {
            lastError = error.msg
            scriptEditor.setSelection({line:error.lineno-1,ch:0}, {line:error.lineno,ch:0});
        }
        currentEvent = 0;
        $('#stopButton span').html('Stop');        
        animate();
    }).header("Content-Type","application/x-www-form-urlencoded").send("POST",$.param(params));
}

function doSave() {
    if ($('#stopButton span').html() == 'Stop') {        
        doStop();
    }
    if (dirty) {
        name = $('#name').val()
        if (name.length) {
            $('*').css('cursor','wait');
            $("#saveButton").attr("disabled", "disabled");
            params = { name: name, script: scriptEditor.getValue(), viz:vizEditor.getValue() }
            d3.json("/save", function(data) {
                $('*').css('cursor','auto');
                $("#saveButton").removeAttr("disabled");
                outputArea.setValue(data['result']);
                dirty = nameChanged = false
                $('#saveButton').removeClass('shown').addClass('hidden')
                window.location = '/show?name=' + name;
            }).header("Content-Type","application/x-www-form-urlencoded").send("POST",$.param(params));
        }
        else {
            window.alert('Please choose a name for your algorithm. Then save again')
        }
    }
    else {
        window.alert('No changes to save.')
    }
}

function doUpdate() {
    if (dirty) {
        name = $('#name').val()
        $('*').css('cursor','wait');
        $("#saveButton").attr("disabled", "disabled");
        params = { name: name, script: sourceEditor.getValue() }
        d3.json("/update", function(data) {
            $('*').css('cursor','auto');
            $("#saveButton").removeAttr("disabled");
            dirty = false
            $('#saveButton').removeClass('shown').addClass('hidden')
            window.alert(data)
        }).header("Content-Type","application/x-www-form-urlencoded").send("POST",$.param(params));
    }
    else {
        window.alert('No changes to save.')
    }
}

function doChange() {
    dirty = true
    $('#saveButton').removeClass('hidden').addClass('shown')
}

function doNameChange() {
    nameChanged = true
    doChange()
}

function doDelete() {
    if ($('#stopButton span').html() == 'Stop') {        
        doStop();
    }
    if (confirm('Are you certain you want to delete this algorithm?\n' +
                'This delete operation cannot be undone. Continue?')) {
        d3.json("/delete?name=" +  $('#name').val(), function(data) {
            outputArea.setValue(data['result']);
            window.location = '/user';
        })
    }
}

function doShare() {
    if ($('#stopButton span').html() == 'Stop') {        
        doStop();
    }
    if (confirm('Are you certain you want to share this algorithm?\n' +
                'This publishes your code to all other users. Continue?')) {
        d3.json("/share?name=" +  $('#name').val(), function(data) {
            outputArea.setValue(data['result']);
        })
    }
}

STEPS = {
    'Fast': 20,
    'Medium': 100,
    'Slow': 200,
    'Snail': 400,
    'Molasses': 800,
}

DELAY = {
    'Fast': 1,
    'Medium': 10,
    'Slow': 50,
    'Snail': 200,
    'Molasses': 1000,
}

function animate() {
    speed = $('#speed').val() || 'Fast'
    last = events.length - 1;
    step = Math.max(1, Math.round(Math.random() * events.length/STEPS[speed]));
    if (currentEvent < last) {
        currentEvent = Math.min(currentEvent + step, last);
        showEvent();
        setTimeout(arguments.callee, DELAY[speed])
    }
    else {
        $('#stopButton span').html('Play');        
    }
}

function doToggleVimMode() {
    createEditors()
}

function doStop() {
    if ($('#stopButton span').html() == 'Play') {        
        $('#stopButton span').html('Stop');        
        if (currentEvent == events.length-1) {
            currentEvent = 0;
        }
        animate();
    }
    else {
        currentEvent = events.length - 1;
        $('#stopButton span').html('Play');        
        setTimeout(showEvent, 1);
    }
}

function T(x,y,txt,size,font,color) {
    canvas.append('text').attr('x', x)
        .attr('y', y)
        .text(txt)
        .attr("font-size", ''+size+'px')
        .attr("font-family", font)
        .attr("fill", color);
}

function L(x1,y1,x2,y2,color,width) {
    canvas.append('line')
        .attr('x1', x1)
        .attr('y1', y1)
        .attr('x2', x2)
        .attr('y2', y2)
        .attr('stroke', color)
        .attr('stroke-width', width);
}

function R(x,y,w,h,fill,border) {
    canvas.append('rect')
        .attr('x', x)
        .attr('y', y)
        .attr('width', w)
        .attr('height', h)
        .attr('fill', fill)
        .attr('stroke', border);
}

function C(x,y,r,fill,border) {
    canvas.append('circle')
        .attr('cx', x)
        .attr('cy', y)
        .attr('r', r)
        .attr('fill', fill)
        .attr('stroke', border);
}

function A(x,y,r1,r2,start,end,color) {
    canvas.append('path')
        .attr('d', 
            d3.svg.arc()
                .innerRadius(r1)
                .outerRadius(r2)
                .startAngle(start)
                .endAngle(end)
        )
        .attr('transform', "translate("+x+','+y+")")
        .attr('fill', color);
}


function doVizHelp() {
    if ($('#stopButton span').html() == 'Stop') {        
        doStop()
    }
    function showHelp() {
      outputArea.setValue(
          "Python Algorithm Visualization Help\n" +
          "--------------------------------------------------------------\n\n" +
          "The visualization script in the bottom left visualizes the code in the top left while it runs. " +
          "You can refer to all local variables used in the algorithm above. " + 
          "If an undefined local or other error is reached, the visualization script stops. " + 
          "Enable 'Show Errors' to show the errors causing the visualization script to stop. " +
          "\n" +
          "\nThe visualization script is executed once for each executed line in the algorithm. " +
          "When the script runs, you can check the value of <b>__lineno__</b> to conditionally run " +
          "a subset of your script to make the visualization act more like a breakpoint. " +
          "\nYou can include arbitrary Python code, including defining helper functions." +
          "\n" +
          "\nAvailable values/primitives:" + 
          "\n * __lineno__" +
          "\n * beep(frequency, milliseconds)" +
          "\n * text(x, y, txt, size=13, font='Arial', color='black')" +
          "\n * line(x1, y1, x2, y2, color='black', width=1)" +
          "\n * rect(x, y, w, h, fill='white', border='black')" +
          "\n * circle(x, y, radius, fill='white', border='black')" +
          "\n * arc(cx, cy, innerRadius, outerRadius, startAngle, endAngle, color='black')" +
          "\n * barchart(x, y, w, h, items, highlight=-1, scale=1, " +
          "\n                                   fill='black', border='black')" +
          ""
      )
    }
    setTimeout(showHelp, 1)
}

function showRendering(script, div, w, h, scale) {
    if (script) {
        $(div).html('')
        svg = d3.select(div)
            .append("svg")
            .attr("width", w)
            .attr("height", h)
        canvas = svg.append('g')
            .attr("transform", "scale("+scale+")");

        try {
            eval(script);
        }
        catch(e) {
            T(100, 100, 'INTERNAL ERROR: ', 15, 'Arial', 'red');
            T(100, 120, ''+e, 15, 'Arial', 'red');
            T(100, 140, ''+script, 15, 'Arial', 'black');
        }
    }
}

function showEvent() {
    e = events[currentEvent];
    scriptEditor.setSelection({line:e[0]-1,ch:0}, {line:e[0],ch:0});
    showRendering(e[1], "#rendering", 600, 445, 1.0);
    progress.innerText = 'Step ' + (currentEvent+1) + ' of ' + events.length
    $('#slider').slider('value',currentEvent);        
    output = OUTPUT
    for (n=0; n<=currentEvent; n++) {
        output += events[n][2];
    }
    if (output) {
        outputArea.setValue(output + lastError);
    }
    lastEvent = currentEvent
}

function doNextStep() {
    if (currentEvent < events.length-1) {
        currentEvent += 1;
        showEvent();
    }
}

function doPreviousStep() {
    if (currentEvent > 0) {
        currentEvent -= 1;
        showEvent();
    }
}

function editor(name, width, height, readonly) {
    var keys = {
        "Ctrl-Enter": function(instance) { doRunScript(); },
        "F9": function(instance) { doRunScript(); }
    }
    var features = readonly ? { 
        lineWrapping: true, extraKeys: keys
    } : {
        lineNumbers: true, indentUnit: 4, autofocus: true, indentWithTabs: false,
        enterMode: "keep", tabMode: "shift", showCursorWhenSelecting: true,
        extraKeys: keys, 
        theme: "pastel-on-dark",
    }
    element = document.getElementById(name)
    if (element) {
        var editor = CodeMirror.fromTextArea(element, features);
        editor.setSize(width, height);
        if (!readonly) {
            editor.on('change',  function(cm, change) { setTimeout(doChange,500) })
        }
        return editor
    }
}

function setReadOnly(readOnly) {
    scriptEditor.setOption('readOnly', readOnly);
    vizEditor.setOption('readOnly', readOnly);
}

function doToggleVimMode() {
    if ($('input[name=vim]').is(':checked')) {
        scriptEditor.setOption('keyMap', 'vim');
        vizEditor.setOption('keyMap', 'vim');
    }
    else {
        scriptEditor.setOption('keyMap', 'default');
        vizEditor.setOption('keyMap', 'default');
    }
    scriptEditor.focus()
}

function doToggleShowErrors() {
    showVizErrors = $('input[name=showErrors]').is(':checked')
    doRunScript()
}

setTimeout(initPyAlgoViz, 1)

try {
    sourceEditor = editor('source', $(window).width()-50, $(window).height()-50, false);
    sourceEditor.setOption('keyMap', 'vim');
    sourceEditor.setOption('readOnly', false);
} catch(e) {
}

scriptEditor = editor('script', 600, 450, false);
vizEditor = editor('visualization', 600, 450, false);
doToggleVimMode()
outputArea = editor('output', 600, 450, true);

setTimeout(initAudio, 1500);

$("#slider").slider({value:0,max:0});
$("#saveButton").button();
$("#openButton").button();
$("#runButton").button();
$("#nextButton").button();
$("#shareButton").button();
$("#helpVizButton").button();
$("#deleteButton").button();
$("#previousButton").button();
$("#stopButton").button();

window.onbeforeunload = function () {
    if (dirty) {
        return "You have unsaved changes..."
    }
}
if (scriptEditor.getValue()) {
    doRunScript();
}

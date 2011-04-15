#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright (C) 2007-2009 Parisson
# Copyright (c) 2007 Olivier Guilyardi <olivier@samalyse.com>
# Copyright (c) 2007-2009 Guillaume Pellerin <pellerin@parisson.com>
#
# This file is part of TimeSide.

# TimeSide is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

# TimeSide is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with TimeSide.  If not, see <http://www.gnu.org/licenses/>.

# Author: Paul Brossier <piem@piem.org>

from timeside.core import Processor, implements, interfacedoc
from timeside.api import IDecoder
from numpy import array, frombuffer, getbuffer, float32, append
from timeside.decoder.old import *

from timeside.decoder.sink import *

import pygst
pygst.require('0.10')
import gst
import gobject
gobject.threads_init()

class FileDecoder(Processor):
    """ gstreamer-based decoder """
    implements(IDecoder)

    # duration ms, before discovery process times out
    MAX_DISCOVERY_TIME = 3000

    audioformat = None
    audiochannels = None
    audiorate = None
    audionframes = None
    mimetype = ''

    # IProcessor methods

    @staticmethod
    @interfacedoc
    def id():
        return "gstreamerdec"

    def setup(self, channels = None, samplerate = None, nframes = None):
        # the output data format we want
        caps = "audio/x-raw-float, width=32"

        src = gst.element_factory_make('uridecodebin')
        src.set_property('uri', self.uri)
        src.connect('pad-added', self.source_pad_added_cb)

        conv = gst.element_factory_make('audioconvert')
        self.conv = conv
        self.apad = self.conv.get_pad('sink')

        capsfilter = gst.element_factory_make('capsfilter')
        capsfilter.set_property('caps', gst.caps_from_string(caps))

        sink = TimesideSink("sink")
        sink.set_property("hopsize", 8*1024)
        sink.set_property("sync", False)
        
        self.pipe = '''uridecodebin uri="%s" name=src
            ! audioconvert
            ! %s
            ! timesidesink name=sink sync=False ''' % (self.uri, caps)

        self.sink = sink
        # TODO
        #self.sink.set_property('emit-signals', True)

        self.pipeline = gst.Pipeline()
        self.pipeline.add(src, conv, capsfilter, sink)

        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message::eos', self.on_eos)
        self.bus.connect('message::tag', self.on_tag)
        self.bus.connect('message::error', self.on_error)

        gst.element_link_many(conv, capsfilter, sink)

        self.mainloop = gobject.MainLoop()

        # start pipeline
        self.pipeline.set_state(gst.STATE_PLAYING)
        self.mainloop.run()

    def source_pad_added_cb(self, src, pad):
        name = pad.get_caps()[0].get_name()
        if name == 'audio/x-raw-float' or name == 'audio/x-raw-int':
            if not self.apad.is_linked():
                pad.link(self.conv.get_pad("sink"))

    def on_eos(self, bus, msg):
        #print 'on_eos'
        self.pipeline.set_state(gst.STATE_NULL)
        self.mainloop.quit()

    def on_tag(self, bus, msg):
        taglist = msg.parse_tag()
        """
        print 'on_tag:'
        for key in taglist.keys():
            print '\t%s = %s' % (key, taglist[key])
        """

    def on_error(self, bus, msg):
        error = msg.parse_error()
        print 'on_error:', error[1]
        self.mainloop.quit()

    @interfacedoc
    def channels(self):
        return  self.audiochannels

    @interfacedoc
    def samplerate(self):
        return self.audiorate

    @interfacedoc
    def nframes(self):
        return self.audionframes

    @interfacedoc
    def process(self, frames = None, eod = False):
        try:
            #buf = self.sink.emit('pull-buffer')                
            buf = self.sink.pull()
        except SystemError, e:
            # should never happen
            print 'SystemError', e
            return array([0.]), True
        if buf == None:
            return array([0.]), True
        return self.gst_buffer_to_numpy_array(buf), False

    @interfacedoc
    def release(self):
        # nothing to do for now
        pass

    ## IDecoder methods

    @interfacedoc
    def __init__(self, uri):
        # is this a file?
        import os.path
        if os.path.exists(uri):
            # get the absolute path
            uri = os.path.abspath(uri)
            # first run the file/uri through the discover pipeline
            self.discover(uri)
            # and make a uri of it
            from urllib import quote
            self.uri = 'file://'+quote(uri)
        else:
            self.uri = uri

    @interfacedoc
    def format(self):
        # TODO check
        if self.mimetype == 'application/x-id3':
            self.mimetype = 'audio/mpeg'
        return self.mimetype

    @interfacedoc
    def encoding(self):
        # TODO check
        return self.mimetype.split('/')[-1]

    @interfacedoc
    def resolution(self):
        # TODO check: width or depth?
        return self.audiowidth

    @interfacedoc
    def metadata(self):
        # TODO check
        return self.tags

    ## gst.extend discoverer

    def discover(self, path):
        """ gstreamer based helper function to get file attributes """
        from gst.extend import discoverer
        d = discoverer.Discoverer(path, timeout = self.MAX_DISCOVERY_TIME)
        d.connect('discovered', self.discovered)
        self.mainloop = gobject.MainLoop()
        d.discover()
        self.mainloop.run()

    def discovered(self, d, is_media):
        """ gstreamer based helper executed upon discover() completion """
        if is_media and d.is_audio:
            # copy the discoverer attributes to self
            self.audiorate = d.audiorate
            self.mimetype= d.mimetype
            self.audiochannels = d.audiochannels
            self.audiowidth = d.audiowidth
            # conversion from time in nanoseconds to frames
            from math import ceil
            duration = d.audiorate * d.audiolength * 1.e-9
            self.audionframes = int (ceil ( duration ) )
            self.tags = d.tags
        elif not d.is_audio:
            print "error, no audio found!"
        else:
            print "fail", path
        self.mainloop.quit()

    def gst_buffer_to_numpy_array(self, buf):
        """ gstreamer buffer to numpy array conversion """
        chan = self.audiochannels
        samples = frombuffer(buf.data, dtype=float32)
        samples.resize([len(samples)/chan, chan])
        return samples

#! /usr/bin/env python

from unit_timeside import unittest, TestRunner
from timeside.plugins.decoder.file import FileDecoder
from timeside.core import get_processor

from timeside.core.tools.test_samples import samples


class TestEssentiaDissonance(unittest.TestCase):

    def setUp(self):
        self.analyzer = get_processor('essentia_dissonance')()

    def testOnC4Scale(self):
        "runs on C4 scale"
        self.source = samples["C4_scale.wav"]

    def tearDown(self):
        decoder = FileDecoder(self.source)
        (decoder | self.analyzer).run()
        self.assertAlmostEqual(self.analyzer.results['essentia_dissonance'].data_object.value.mean(), 0.16, places=2)


if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())
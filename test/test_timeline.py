from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tempfile
import unittest
import warnings

import os
import numpy as np
import torch
import bluefog.torch as bf
from bluefog.common import topology_util
from bluefog.common.util import env

class TimelineTests(unittest.TestCase):
    """
    Tests for timeline
    """

    def __init__(self, *args, **kwargs):
        super(TimelineTests, self).__init__(*args, **kwargs)
        warnings.simplefilter('module')
        self.temp_file = './timeline_temp'

    def setUp(self):
        with env(BLUEFOG_TIMELINE=self.temp_file):
            bf.init()

    def __del__(self):
        # file_name is just a temprary file generated in bluefog timeline
        file_name = f"{self.temp_file}{bf.rank()}.json"
        if os.path.exists(file_name):
            os.remove(file_name)

    def test_timeline_neighbor_allreduce(self):
        x = torch.FloatTensor(10, 10).fill_(1).mul_(bf.rank())
        for _ in range(50):
            x = bf.neighbor_allreduce(x, name='test_neighbor_allreduce')

        file_name = f"{self.temp_file}{bf.rank()}.json"
        with open(file_name, 'r') as tf:
            timeline_text = tf.read()
            assert 'MPI_NEIGHBOR_ALLREDUCE' in timeline_text, timeline_text
            assert 'ENQUEUE_NEIGHBOR_ALLREDUCE' in timeline_text, timeline_text

    def test_timeline_push_sum(self):
        # Use win_accumulate to simulate the push-sum algorithm (sync).
        bf.set_topology(topology_util.StarGraph(bf.size()))
        outdegree = len(bf.out_neighbor_ranks())
        indegree = len(bf.in_neighbor_ranks())
        # we append the p at the last of data.
        x = torch.Tensor([bf.rank()/(indegree+1), 1.0/bf.size()/(indegree+1)])

        # Remember we do not create buffer with 0.
        bf.win_create(x, name="x_buff")
        x = bf.win_sync_then_collect(name="x_buff")

        for _ in range(100):
            bf.win_accumulate(
                x, name="x_buff",
                dst_weights={rank: 1.0 / (outdegree + 1)
                             for rank in bf.out_neighbor_ranks()},
                require_mutex=True)
            x.div_(1+outdegree)
            x = bf.win_sync_then_collect(name="x_buff")

        bf.barrier()
        # Do not forget to sync at last!
        x = bf.win_sync_then_collect(name="x_buff")

        file_name = f"{self.temp_file}{bf.rank()}.json"
        with open(file_name, 'r') as tf:
            timeline_text = tf.read()
            assert 'MPI_WIN_ACCUMULATE' in timeline_text, timeline_text
            assert 'ENQUEUE_WIN_ACCUMULATE' in timeline_text, timeline_text

if __name__ == "__main__":
    unittest.main()

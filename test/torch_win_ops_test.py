from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import itertools
import unittest
import time
import warnings
warnings.simplefilter("ignore")

import numpy as np
import torch

from common import mpi_env_rank_and_size
import bluefog.torch as bf
from bluefog.common import topology_util


EPSILON = 1e-5
TEST_ON_GPU = False and torch.cuda.is_available()

class WinOpsTests(unittest.TestCase):
    """
    Tests for bluefog/torch/mpi_ops.py on one-sided communication.
    """

    def __init__(self, *args, **kwargs):
        super(WinOpsTests, self).__init__(*args, **kwargs)
        warnings.simplefilter("module")

    def setUp(self):
        bf.init()

    def tearDown(self):
        assert bf.win_free()

    @staticmethod
    def cast_and_place(tensor, dtype):
        if dtype.is_cuda:
            device_id = bf.local_rank()
            device_id = 0
            return tensor.cuda(device_id).type(dtype)
        return tensor.type(dtype)

    def test_win_create_and_sync_and_free(self):
        """Test that the window create and free objects correctly."""
        size = bf.size()
        rank = bf.rank()
        dtypes = [torch.FloatTensor, torch.DoubleTensor]
        if TEST_ON_GPU:
            dtypes += [torch.cuda.FloatTensor]

        # By default, we use power two ring topology.
        num_indegree = int(np.ceil(np.log2(size)))

        dims = [1, 2, 3]
        for dtype, dim in itertools.product(dtypes, dims):
            tensor = torch.FloatTensor(*([23] * dim)).fill_(1).mul_(rank)
            tensor = self.cast_and_place(tensor, dtype)
            window_name = "win_create_{}_{}".format(dim, dtype)
            is_created = bf.win_create(tensor, window_name)
            assert is_created, "bf.win_create do not create window object successfully."

            sync_result = bf.win_sync(window_name)
            assert (list(sync_result.shape) == [23] * dim), (
                "bf.win_sync produce wrong shape tensor.")
            assert (sync_result.data.min() == rank), (
                "bf.win_sync produces wrong tensor value " +
                "{}!={} at rank {}.".format(sync_result.data.min(), num_indegree*rank, rank))
            assert (sync_result.data.max() == rank), (
                "bf.win_sync produces wrong tensor value " +
                "{}!={} at rank {}.".format(sync_result.data.max(), num_indegree*rank, rank))

        for dtype, dim in itertools.product(dtypes, dims):
            window_name = "win_create_{}_{}".format(dim, dtype)
            is_freed = bf.win_free(window_name)
            assert is_freed, "bf.win_free do not free window object successfully."

    def test_win_free_all(self):
        dtypes = [torch.FloatTensor, torch.DoubleTensor]
        if TEST_ON_GPU:
            dtypes += [torch.cuda.FloatTensor]

        dims = [1, 2, 3]
        for dtype, dim in itertools.product(dtypes, dims):
            tensor = torch.FloatTensor(*([23] * dim)).fill_(1)
            tensor = self.cast_and_place(tensor, dtype)
            window_name = "win_create_{}_{}".format(dim, dtype)
            is_created = bf.win_create(tensor, window_name)
            assert is_created, "bf.win_create do not create window object successfully."

        is_freed = bf.win_free()
        assert is_freed, "bf.win_free do not free window object successfully."

    def test_win_sync_with_given_weights(self):
        size = bf.size()
        rank = bf.rank()
        if size <= 1:
            warnings.warn(
                "Skip test win_put since the world size should be larger than 1!"
            )
            return
        dtypes = [torch.FloatTensor, torch.DoubleTensor]
        if TEST_ON_GPU:
            dtypes += [torch.cuda.FloatTensor]

        dims = [1, 2, 3]
        for dtype, dim in itertools.product(dtypes, dims):
            tensor = torch.FloatTensor(*([23] * dim)).fill_(1).mul_(rank)
            tensor = self.cast_and_place(tensor, dtype)
            window_name = "win_create_{}_{}".format(dim, dtype)
            is_created = bf.win_create(tensor, window_name)
            assert is_created, "bf.win_create do not create window object successfully."

            # Test simple average rule.
            sync_result = bf.win_sync(window_name,
                                      weights={x: 1.0/(len(bf.in_neighbor_ranks())+1)
                                               for x in bf.in_neighbor_ranks() + [bf.rank()]}
                                      )
            assert (list(sync_result.shape) == [23] * dim), (
                "bf.win_sync (weighted) produces wrong shape tensor.")
            assert (sync_result.data - rank).abs().max() < EPSILON, (
                "bf.win_sync (weighted) produces wrong tensor value " +
                "[{}-{}]!={} at rank {}.".format(sync_result.min(),
                                                 sync_result.max(), rank, rank))

    def test_win_sync_with_default_weights(self):
        size = bf.size()
        rank = bf.rank()
        if size <= 1:
            warnings.warn(
                "Skip test win_put since the world size should be larger than 1!"
            )
            return
        dtypes = [torch.FloatTensor, torch.DoubleTensor]
        if TEST_ON_GPU:
            dtypes += [torch.cuda.FloatTensor]

        bf.set_topology(topology_util.StartGraph(size), is_weighted=True)

        dims = [1, 2, 3]
        for dtype, dim in itertools.product(dtypes, dims):
            tensor = torch.FloatTensor(*([23] * dim)).fill_(1).mul_(rank)
            tensor = self.cast_and_place(tensor, dtype)
            window_name = "win_create_{}_{}".format(dim, dtype)
            is_created = bf.win_create(tensor, window_name)
            assert is_created, "bf.win_create do not create window object successfully."

            # Note the buffers store the copy of original value so they will not change.
            tensor.mul_(2)
            if rank == 0:
                expected_result = rank * 2 / size + rank * (size-1)/size
            else:
                expected_result = rank / size + rank * 2 * (1-1/size)

            sync_result = bf.win_sync(window_name)
            assert (list(sync_result.shape) == [23] * dim), (
                "bf.win_sync (weighted) produces wrong shape tensor.")
            assert (sync_result.data - expected_result).abs().max() < EPSILON, (
                "bf.win_sync (weighted) produces wrong tensor value " +
                "[{}-{}]!={} at rank {}.".format(sync_result.min(),
                                                 sync_result.max(), rank, rank))
        assert bf.win_free()

    def test_win_sync_then_collect(self):
        size = bf.size()
        rank = bf.rank()
        if size <= 1:
            warnings.warn(
                "Skip test win_put since the world size should be larger than 1!"
            )
            return
        dtypes = [torch.FloatTensor, torch.DoubleTensor]
        if TEST_ON_GPU:
            dtypes += [torch.cuda.FloatTensor]

        indegree = int(np.ceil(np.log2(size)))
        expected_result = rank * (indegree+1)

        dims = [1, 2, 3]
        for dtype, dim in itertools.product(dtypes, dims):
            tensor = torch.FloatTensor(*([23] * dim)).fill_(1).mul_(rank)
            tensor = self.cast_and_place(tensor, dtype)
            window_name = "win_sync_collect_{}_{}".format(dim, dtype)

            bf.win_create(tensor, window_name)

            # After the collect ops, the neighbro tensor will become zero.
            # So second win_sync_then_collect should produce the same value.
            for _ in range(2):
                collect_tensor = bf.win_sync_then_collect(window_name)

                assert (list(collect_tensor.shape) == [23] * dim), (
                    "bf.win_sync_then_collect produces wrong shape tensor.")
                assert (collect_tensor.data - expected_result).abs().max() < EPSILON, (
                    "bf.win_sync_then_collect produces wrong tensor value " +
                    "[{}-{}]!={} at rank {}.".format(collect_tensor.min(),
                                                     collect_tensor.max(), rank, rank))

    def test_win_put_blocking(self):
        """Test that the window put operation."""
        size = bf.size()
        rank = bf.rank()
        if size <= 1:
            warnings.warn(
                "Skip test win_put since the world size should be larger than 1!"
            )
            return
        dtypes = [torch.FloatTensor, torch.DoubleTensor]
        if TEST_ON_GPU:
            dtypes += [torch.cuda.FloatTensor]

        # By default, we use power two ring topology.
        outdegree = int(np.ceil(np.log2(size)))
        neighbor_ranks = [(rank - 2**i) %
                          size for i in range(outdegree)]  # in-neighbor
        avg_value = (rank + np.sum(neighbor_ranks)) / float(outdegree+1)

        dims = [1, 2, 3]
        for dtype, dim in itertools.product(dtypes, dims):
            tensor = torch.FloatTensor(*([3] * dim)).fill_(1).mul_(rank)
            tensor = self.cast_and_place(tensor, dtype)
            window_name = "win_put_{}_{}".format(dim, dtype)
            bf.win_create(tensor, window_name)

            bf.win_put_blocking(tensor, window_name)
            bf.barrier()
            sync_result = bf.win_sync(window_name)
            assert (list(sync_result.shape) == [3] * dim), (
                "bf.win_sync after win_put produces wrong shape tensor.")
            assert (sync_result.data - avg_value).abs().max() < EPSILON, (
                "bf.win_sync after win_put produces wrong tensor value " +
                "[{}-{}]!={} at rank {}.".format(sync_result.min(),
                                                 sync_result.max(), avg_value, rank))

        time.sleep(0.5)
        for dtype, dim in itertools.product(dtypes, dims):
            window_name = "win_put_{}_{}".format(dim, dtype)
            is_freed = bf.win_free(window_name)
            assert is_freed, "bf.win_free do not free window object successfully."

    def test_win_put_blocking_with_given_destination(self):
        """Test that the window put operation with given destination."""
        size = bf.size()
        rank = bf.rank()
        if size <= 1:
            warnings.warn(
                "Skip test win_put with given destination " +
                "since the world size should be larger than 1!"
            )
            return
        dtypes = [torch.FloatTensor, torch.DoubleTensor]
        if TEST_ON_GPU:
            dtypes += [torch.cuda.FloatTensor]

        # By default, we use power two ring topology.
        outdegree = int(np.ceil(np.log2(size)))
        # We use given destination to form a (right-)ring.
        avg_value = (rank*outdegree + 1.23*((rank-1) % size)) / float(outdegree+1)

        dims = [1, 2, 3]
        for dtype, dim in itertools.product(dtypes, dims):
            tensor = torch.FloatTensor(*([3] * dim)).fill_(1).mul_(rank)
            tensor = self.cast_and_place(tensor, dtype)
            window_name = "win_put_given_{}_{}".format(dim, dtype)
            bf.win_create(tensor, window_name)
            bf.win_put_blocking(tensor, window_name, {(rank+1) % size: 1.23})
            bf.barrier()
            sync_result = bf.win_sync(window_name)
            assert (list(sync_result.shape) == [3] * dim), (
                "bf.win_sync after win_put given destination produces wrong shape tensor.")
            assert (sync_result.data - avg_value).abs().max() < EPSILON, (
                "bf.win_sync after win_put given destination produces wrong tensor value " +
                "[{}-{}]!={} at rank {}.".format(sync_result.min(),
                                                 sync_result.max(), avg_value, rank))

        time.sleep(0.5)
        for dtype, dim in itertools.product(dtypes, dims):
            window_name = "win_put_given_{}_{}".format(dim, dtype)
            is_freed = bf.win_free(window_name)
            assert is_freed, "bf.win_free do not free window object successfully."

    def test_win_accumulate_blocking(self):
        """Test that the window accumulate operation."""
        size = bf.size()
        rank = bf.rank()
        if size <= 1:
            warnings.warn(
                "Skip test win_accumulate since the world size should be larger than 1!"
            )
            return
        dtypes = [torch.FloatTensor, torch.DoubleTensor]
        if TEST_ON_GPU:
            dtypes += [torch.cuda.FloatTensor]

        # By default, we use power two ring topology.
        outdegree = int(np.ceil(np.log2(size)))
        neighbor_ranks = [(rank - 2**i) %
                          size for i in range(outdegree)]  # in-neighbor
        avg_value = rank + np.sum(neighbor_ranks) / float(outdegree+1)

        dims = [1, 2, 3]
        for dtype, dim in itertools.product(dtypes, dims):
            tensor = torch.FloatTensor(*([3] * dim)).fill_(1).mul_(rank)
            tensor = self.cast_and_place(tensor, dtype)
            window_name = "win_accumulate_{}_{}".format(dim, dtype)
            bf.win_create(tensor, window_name)
            bf.win_accumulate_blocking(tensor, window_name)

            bf.barrier()
            sync_result = bf.win_sync(window_name)

            assert (list(sync_result.shape) == [3] * dim), (
                "bf.win_sync after win_accmulate produces wrong shape tensor.")
            assert (sync_result.data - avg_value).abs().max() < EPSILON, (
                "bf.win_sync after win_accmulate produces wrong tensor value " +
                "[{}-{}]!={} at rank {}.".format(sync_result.min(),
                                                 sync_result.max(), avg_value, rank))

    def test_win_accumulate_blocking_with_given_destination(self):
        """Test that the window accumulate operation with given destination."""
        size = bf.size()
        rank = bf.rank()
        if size <= 1:
            warnings.warn(
                "Skip test win_accumulate since the world size should be larger than 1!"
            )
            return
        dtypes = [torch.FloatTensor, torch.DoubleTensor]
        if TEST_ON_GPU:
            dtypes += [torch.cuda.FloatTensor]

        avg_value = rank + ((rank-1) % size) * 1.23 / 2.0

        dims = [1, 2, 3]
        for dtype, dim in itertools.product(dtypes, dims):
            tensor = torch.FloatTensor(*([3] * dim)).fill_(1).mul_(rank)
            tensor = self.cast_and_place(tensor, dtype)
            window_name = "win_accumulate_{}_{}".format(dim, dtype)
            bf.win_create(tensor, window_name)
            bf.win_accumulate_blocking(tensor, window_name,
                                       dst_weights={(rank+1) % size: 1.23})

            bf.barrier()
            sync_result = bf.win_sync(window_name, weights={(rank-1) % size: 0.5,
                                                            rank: 0.5})

            assert (list(sync_result.shape) == [3] * dim), (
                "bf.win_sync after win_accmulate given destination produces wrong shape tensor.")
            assert (sync_result.data - avg_value).abs().max() < EPSILON, (
                "bf.win_sync after win_accmulate given destination produces wrong tensor value " +
                "[{}-{}]!={} at rank {}.".format(sync_result.min(),
                                                 sync_result.max(), avg_value, rank))

    def test_win_get_blocking(self):
        """Test that the window get operation."""
        size = bf.size()
        rank = bf.rank()
        if size <= 1:
            warnings.warn(
                "Skip test win_get since the world size should be larger than 1!"
            )
            return
        dtypes = [torch.FloatTensor, torch.DoubleTensor]
        if TEST_ON_GPU:
            dtypes += [torch.cuda.FloatTensor]

        # By default, we use power two ring topology.
        indegree = int(np.ceil(np.log2(size)))
        neighbor_ranks = [(rank - 2**i) %
                          size for i in range(indegree)]  # in-neighbor
        avg_value = (rank + np.sum(neighbor_ranks)) / float(indegree+1)

        dims = [1, 2, 3]
        for dtype, dim in itertools.product(dtypes, dims):
            tensor = torch.FloatTensor(*([3] * dim)).fill_(1).mul_(rank)
            tensor = self.cast_and_place(tensor, dtype)
            window_name = "win_get_{}_{}".format(dim, dtype)
            bf.win_create(tensor, window_name)
            bf.win_get_blocking(window_name)
            bf.barrier()
            recv_tensor = bf.win_sync(window_name)

            assert (list(tensor.shape) == [3] * dim), (
                "bf.win_get produce wrong shape tensor.")
            assert (recv_tensor.data - avg_value).abs().max() < EPSILON, (
                "bf.win_get produce wrong tensor value " +
                "[{}-{}]!={} at rank {}.".format(
                    recv_tensor.min(), recv_tensor.max(), avg_value, rank))

    def test_win_get_blocking_with_given_sources(self):
        """Test that the window get operation with given sources."""
        size = bf.size()
        rank = bf.rank()
        if size <= 1:
            warnings.warn(
                "Skip test win_get_given_sources " +
                "since the world size should be larger than 1!"
            )
            return
        dtypes = [torch.FloatTensor, torch.DoubleTensor]
        if TEST_ON_GPU:
            dtypes += [torch.cuda.FloatTensor]

        # We use given destination to form a (right-)ring.
        avg_value = (rank + 1.23*((rank-1) % size)) / float(2)

        dims = [1, 2, 3]
        for dtype, dim in itertools.product(dtypes, dims):
            tensor = torch.FloatTensor(*([3] * dim)).fill_(1).mul_(rank)
            tensor = self.cast_and_place(tensor, dtype)
            window_name = "win_get_given_{}_{}".format(dim, dtype)
            bf.win_create(tensor, window_name)
            bf.win_get_blocking(window_name, src_weights={
                                (rank-1) % size: 1.23})
            bf.barrier()
            recv_tensor = bf.win_sync(window_name, weights={(rank-1) % size: 0.5,
                                                            rank: 0.5})

            assert (list(recv_tensor.shape) == [3] * dim), (
                "bf.win_get with given sources produces wrong shape tensor.")
            assert (recv_tensor.data - avg_value).abs().max() < EPSILON, (
                "bf.win_get with given sources produces wrong tensor value " +
                "[{}-{}]!={} at rank {}.".format(recv_tensor.min(),
                                                 recv_tensor.max(), avg_value, rank))


if __name__ == "__main__":
    unittest.main()
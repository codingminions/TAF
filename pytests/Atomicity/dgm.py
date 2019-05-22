from basetestcase import BaseTestCase
from couchbase_helper.documentgenerator import doc_generator
from BucketLib.BucketOperations import BucketHelper
import time


class Bucket_DGM_Tests(BaseTestCase):
    def setUp(self):
        super(Bucket_DGM_Tests, self).setUp()
        self.key = 'test_docs'.rjust(self.key_size, '0')
        nodes_init = self.cluster.servers[1:self.nodes_init] \
            if self.nodes_init != 1 else []
        self.task.rebalance([self.cluster.master], nodes_init, [])
        self.cluster.nodes_in_cluster.extend(
            [self.cluster.master] + nodes_init)
        self.bucket_util.create_default_bucket(
            ram_quota=self.bucket_size, replica=self.num_replicas,
            maxTTL=self.maxttl, compression_mode=self.compression_mode)
        self.bucket_util.add_rbac_user()

        doc_create = doc_generator(
            self.key, 0, self.num_items, doc_size=self.doc_size,
            doc_type=self.doc_type, vbuckets=self.vbuckets)
        self.print_cluster_stat_task = self.cluster_util.async_print_cluster_stats()
        for bucket in self.bucket_util.buckets:
            task = self.task.async_load_gen_docs(
                self.cluster, bucket, doc_create, "create", 0,
                persist_to=self.persist_to, replicate_to=self.replicate_to,
                batch_size=10, process_concurrency=8)
            self.task.jython_task_manager.get_task_result(task)
            # Verify initial doc load count
            self.bucket_util._wait_for_stats_all_buckets()
            self.bucket_util.verify_stats_all_buckets(self.num_items)
        self.log.info("========= Finished Bucket_DGM_Tests setup =======")

    def tearDown(self):
        super(Bucket_DGM_Tests, self).tearDown()

    def test_dgm_with_Atomicity(self):
        # Prepare DGM scenario
        bucket = self.bucket_util.get_all_buckets()[0]
        num_items = self.task.load_bucket_into_dgm(
            self.cluster, bucket, self.key, self.num_items,
            self.active_resident_threshold, batch_size=10,
            process_concurrency=8,
            persist_to=self.persist_to, replicate_to=self.replicate_to)

#         gen_create = doc_generator(self.key, num_items,
#                                    num_items+self.num_items)

#         # Perform operation through transaction after DGM
#         tasks = list()
#         tasks.append(self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
#                                              gen_create,"create",
#                                              batch_size=10,timeout_secs=self.sdk_timeout,process_concurrency=8,
#                                              retries=self.sdk_retries, transaction_timeout=200, commit=True))
#         
#         for task in tasks:
#             self.task.jython_task_manager.get_task_result(task)
#             
#         time.sleep(10)

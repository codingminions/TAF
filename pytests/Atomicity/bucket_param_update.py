from basetestcase import BaseTestCase
from couchbase_helper.documentgenerator import doc_generator
from BucketLib.BucketOperations import BucketHelper
import time


class Bucket_param_test(BaseTestCase):
    def setUp(self):
        super(Bucket_param_test, self).setUp()
        self.transaction_timeout = self.input.param("transaction_timeout", 100)
        self.transaction_commit = self.input.param("transaction_commit", True)
        self.op_type = self.input.param("op_type", 'create')
        self.start_doc_for_insert = 0
        self.key = 'test-doc'.rjust(self.key_size, '0')
        nodes_init = self.cluster.servers[1:self.nodes_init] \
            if self.nodes_init != 1 else []
        self.task.rebalance([self.cluster.master], nodes_init, [])
        self.cluster.nodes_in_cluster.extend(
            [self.cluster.master] + nodes_init)
        self.bucket_util.create_default_bucket(
            replica=self.num_replicas, compression_mode=self.compression_mode)
        self.bucket_util.add_rbac_user()
        self.src_bucket = self.bucket_util.get_all_buckets()
        # Reset active_resident_threshold to avoid further data load as DGM
        self.active_resident_threshold = 0

        doc_create = doc_generator('test-d', 0, self.num_items,
                                   doc_size=self.doc_size,
                                   doc_type="json",
                                   vbuckets=self.vbuckets)
        for bucket in self.bucket_util.buckets:
            task = self.task.async_load_gen_docs(
                self.cluster, bucket, doc_create, "create", 0,
                persist_to=self.persist_to, replicate_to=self.replicate_to,
                batch_size=10, process_concurrency=8)
            self.task.jython_task_manager.get_task_result(task)
            # Verify initial doc load count
            time.sleep(20)
        self.log.info("==========Finished Bucket_param_test setup========")

    def tearDown(self):
        super(Bucket_param_test, self).tearDown()

    def generic_replica_update(self, doc_ops, bucket_helper_obj,
                               replicas_to_update):
        update_replicateTo_persistTo = self.input.param(
            "update_replicateTo_persistTo", False)
        def_bucket = self.bucket_util.get_all_buckets()[0]
        

        for replica_num in replicas_to_update:
            tasks = list()
            # Creating doc creator to be used by test cases
            doc_create = doc_generator(self.key, self.start_doc_for_insert,
                                       self.num_items,
                                       doc_size=self.doc_size,
                                       doc_type="json",
                                       vbuckets=self.vbuckets)

            self.log.info("Updating replica count of bucket to {0}"
                          .format(replica_num))

            if update_replicateTo_persistTo:
                if self.self.durability_level is None:
                    self.replicate_to = replica_num
                    self.persist_to = replica_num + 1

            bucket_helper_obj.change_bucket_props(def_bucket.name,
                                                  replicaNumber=replica_num)

# create, create;update, create;update;delete
            tasks.append(self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             doc_create,self.op_type,
                                             batch_size=10,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit))

            # Start rebalance task with doc_ops in parallel
            tasks.append(self.task.async_rebalance(self.cluster.servers,
                                                   [], []))
            self.num_items *= 2
            self.start_doc_for_insert = self.num_items

            for task in tasks:
                self.task.jython_task_manager.get_task_result(task)
            time.sleep(20)


    def test_replica_update(self):
        if self.nodes_init < 2:
            self.log.error("Test not supported for < 2 node cluster")
            return

        doc_ops = self.input.param("doc_ops", None)
        if doc_ops is None:
            doc_ops = list()
        else:
            doc_ops = doc_ops.split(":")

        bucket_helper = BucketHelper(self.cluster.master)

        # Replica increment tests
        self.generic_replica_update(doc_ops, bucket_helper,
                                    range(1, min(3, self.nodes_init)))
        # Replica decrement tests
        self.generic_replica_update(doc_ops, bucket_helper,
                                    range(min(3, self.nodes_init), 1, -1))

import time

from membase.api.exception import RebalanceFailedException
from membase.api.rest_client import RestConnection
from Atomicity.rebalance_new.rebalance_base import RebalanceBaseTest
from remote.remote_util import RemoteMachineShellConnection


class RebalanceInTests(RebalanceBaseTest):

    def setUp(self):
        super(RebalanceInTests, self).setUp()

    def tearDown(self):
        super(RebalanceInTests, self).tearDown()
    
    def test_rebalance_in_out_after_mutation(self):
        self.transaction_timeout = self.input.param("transaction_timeout", 100)
        self.transaction_commit = self.input.param("transaction_commit", True)
        self.def_bucket= self.bucket_util.get_all_buckets()
        gen = self.get_doc_generator(0, self.num_items)
        task = self.task.async_load_gen_docs_atomicity(self.cluster, self.def_bucket,
                                            self.gen_update, "rebalance_update" , exp=0,
                                            batch_size=10,
                                            process_concurrency=8,
                                            replicate_to=self.replicate_to,
                                            persist_to=self.persist_to, timeout_secs=self.sdk_timeout,
                                            retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level)
        servs_in = self.cluster.servers[self.nodes_init:self.nodes_init + self.nodes_in]
        servs_out = self.cluster.servers[self.nodes_init - self.nodes_out:self.nodes_init]
        result_nodes = list(set(self.cluster.servers[:self.nodes_init] + servs_in) - set(servs_out))
        self.task_manager.get_task_result(task)

        self.sleep(20)
        prev_vbucket_stats = self.bucket_util.get_vbucket_seqnos(self.cluster.servers[:self.nodes_init], self.bucket_util.buckets)
        prev_failover_stats = self.bucket_util.get_failovers_logs(self.cluster.servers[:self.nodes_init], self.bucket_util.buckets)
        disk_replica_dataset, disk_active_dataset = self.bucket_util.get_and_compare_active_replica_data_set_all(
           self.cluster.servers[:self.nodes_init], self.bucket_util.buckets, path=None)
        self.bucket_util.compare_vbucketseq_failoverlogs(prev_vbucket_stats, prev_failover_stats)
        self.add_remove_servers_and_rebalance(servs_in, servs_out)
        self.sleep(120)
#         self.bucket_util.verify_stats_all_buckets(self.num_items, timeout=120)
#         self.bucket_util.verify_cluster_stats(self.num_items, check_ep_items_remaining=True)
        new_failover_stats = self.bucket_util.compare_failovers_logs(prev_failover_stats, result_nodes, self.bucket_util.buckets)
        new_vbucket_stats = self.bucket_util.compare_vbucket_seqnos(prev_vbucket_stats, result_nodes, self.bucket_util.buckets,
                                                       perNode=False)
        self.bucket_util.compare_vbucketseq_failoverlogs(new_vbucket_stats, new_failover_stats)
        self.sleep(30)
        self.bucket_util.data_analysis_active_replica_all(disk_active_dataset, disk_replica_dataset, result_nodes, self.bucket_util.buckets,
                                             path=None)
        self.bucket_util.verify_unacked_bytes_all_buckets()
        nodes = self.cluster.nodes_in_cluster 
        
    def test_rebalance_in_with_ops(self):
        gen_create = self.get_doc_generator(self.num_items, self.num_items * 2)
        gen_delete = self.get_doc_generator(self.num_items / 2, self.num_items)
        servs_in = [self.cluster.servers[i + self.nodes_init]
                    for i in range(self.nodes_in)]
        tasks = []
        self.def_bucket= self.bucket_util.get_all_buckets()
        rebalance_task = self.task.async_rebalance(self.cluster.servers[:self.nodes_init], servs_in, [])
        tasks.append(rebalance_task)
        self.transaction_timeout = self.input.param("transaction_timeout", 100)
        self.transaction_commit = self.input.param("transaction_commit", True)
        time.sleep(15)
        
        
        if(self.doc_ops is not None):
            if("update" in self.doc_ops):
                tasks.append(self.task.async_load_gen_docs_atomicity(
                          self.cluster, self.def_bucket, self.gen_update, "rebalance_update",0,
                          batch_size=20,process_concurrency=8,replicate_to=self.replicate_to,
                                            persist_to=self.persist_to,timeout_secs=self.sdk_timeout,retries=self.sdk_retries,
                          transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level))
       
            if("create" in self.doc_ops):
                tasks.append(self.task.async_load_gen_docs_atomicity(
                        self.cluster,self.bucket_util.buckets, gen_create, "create",0,
                        batch_size=20,process_concurrency=8,replicate_to=self.replicate_to,
                                            persist_to=self.persist_to,timeout_secs=self.sdk_timeout,retries=self.sdk_retries,
                        transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level))
            
            if("delete" in self.doc_ops):
                tasks.append(self.task.async_load_gen_docs_atomicity(
                        self.cluster,self.bucket_util.buckets, gen_delete, "rebalance_delete",0,
                        batch_size=20,timeout_secs=self.sdk_timeout,process_concurrency=8,retries=self.sdk_retries,
                        transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level))
                     
        for task in tasks:
            self.task.jython_task_manager.get_task_result(task)
            # self.log.info("Failed to insert {} number of items after loadgen".format(fail.__len__()))
            #self.num_items += self.num_items - fail.__len__()
        self.cluster.nodes_in_cluster.extend(servs_in)
        self.sleep(60, "Wait for cluster to be ready after rebalance")
        
    def test_rebalance_in_after_ops(self):
        """
        Rebalances nodes into cluster while doing docs ops:create/delete/update

        This test begins by loading a given number of items into the cluster.
        Then adds nodes_in nodes at a time and rebalances that nodes
        into the cluster.
        During the rebalance we perform docs ops(add/remove/update/readd)
        in the cluster( operate with a half of items that were loaded before).
        Once the cluster is rebalanced we wait for the disk queues to drain,
        then verify that there has been no data loss and sum(curr_items) match
        the curr_items_total.
        Once all nodes have been rebalanced in the test is finished.
        """
        gen_update = self.get_doc_generator(0, self.num_items)
        self.transaction_timeout = self.input.param("transaction_timeout", 500)
        self.transaction_commit = self.input.param("transaction_commit", True)
        std = self.std_vbucket_dist or 1.0
        tasks = []
        
        tasks.append(self.task.async_load_gen_docs_atomicity(
                        self.cluster, self.bucket_util.buckets, gen_update, "rebalance_update",0,
                        batch_size=20,timeout_secs=self.sdk_timeout,process_concurrency=8,retries=self.sdk_retries,
                        transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level))
        for task in tasks:
            self.task.jython_task_manager.get_task_result(task)
        servs_in = [self.cluster.servers[i + self.nodes_init] for i in range(self.nodes_in)]
        self.sleep(20)
        #=======================================================================
        # for bucket in self.bucket_util.buckets:
        #     current_items = self.bucket_util.get_bucket_current_item_count(self.cluster, bucket)
        #     self.num_items = current_items
        # self.bucket_util.verify_stats_all_buckets(self.num_items)
        # self.bucket_util._wait_for_stats_all_buckets()
        self.sleep(20)
        #=======================================================================
        prev_failover_stats = self.bucket_util.get_failovers_logs(self.cluster.servers[:self.nodes_init], self.bucket_util.buckets)
        prev_vbucket_stats = self.bucket_util.get_vbucket_seqnos(self.cluster.servers[:self.nodes_init], self.bucket_util.buckets)
        disk_replica_dataset, disk_active_dataset = self.bucket_util.get_and_compare_active_replica_data_set_all(
            self.cluster.servers[:self.nodes_init], self.bucket_util.buckets, path=None)
        self.bucket_util.compare_vbucketseq_failoverlogs(prev_vbucket_stats, prev_failover_stats)
        rebalance = self.task.async_rebalance(self.cluster.servers[:self.nodes_init], servs_in, [])
        self.task.jython_task_manager.get_task_result(rebalance)
        self.sleep(60)
        self.cluster.nodes_in_cluster.extend(servs_in)
        #=======================================================================
        # for bucket in self.bucket_util.buckets:
        #     current_items = self.bucket_util.get_bucket_current_item_count(self.cluster, bucket)
        #     self.num_items = current_items
        # self.bucket_util.verify_stats_all_buckets(self.num_items, timeout=120)
        # self.bucket_util.verify_cluster_stats(self.num_items, check_ep_items_remaining=True)
        #=======================================================================
        new_failover_stats = self.bucket_util.compare_failovers_logs(
            prev_failover_stats, self.cluster.servers[:self.nodes_in + self.nodes_init],
            self.bucket_util.buckets)
        
        new_vbucket_stats = self.bucket_util.compare_vbucket_seqnos(
            prev_vbucket_stats, self.cluster.servers[:self.nodes_in + self.nodes_init],
            self.bucket_util.buckets)
        
        self.bucket_util.compare_vbucketseq_failoverlogs(new_vbucket_stats, new_failover_stats)
        self.sleep(30)
        
        self.bucket_util.data_analysis_active_replica_all(
            disk_active_dataset, disk_replica_dataset,
            self.cluster.servers[:self.nodes_in + self.nodes_init],
            self.bucket_util.buckets, path=None)
        self.sleep(30)

        self.bucket_util.verify_unacked_bytes_all_buckets()
        
        nodes = self.cluster_util.get_nodes_in_cluster(self.cluster.master)
        self.bucket_util.vb_distribution_analysis(
            servers=nodes, buckets=self.bucket_util.buckets,
            num_replicas=self.num_replicas,
            std=std, total_vbuckets=self.vbuckets)
        
    def rebalance_in_with_failover_full_addback_recovery(self):
        """
        Rebalances nodes in with failover and full recovery add back of a node

        This test begins by loading a given number of items into the cluster.
        Then adds nodes_in nodes at a time and rebalances that nodes
        into the cluster.
        During the rebalance we perform docs ops(add/remove/update/readd)
        in the cluster( operate with a half of items that were loaded before).
        Once the cluster is rebalanced we wait for the disk queues to drain,
        then verify that there has been no data loss and sum(curr_items)
        match the curr_items_total.
        Once all nodes have been rebalanced in the test is finished.
        """
        self.transaction_timeout = self.input.param("transaction_timeout", 100)
        self.transaction_commit = self.input.param("transaction_commit", True)
        
        gen_update = self.get_doc_generator(0, self.num_items)
        std = self.std_vbucket_dist or 1.0
        tasks = []
        tasks.append(self.task.async_load_gen_docs_atomicity(
                        self.cluster, self.bucket_util.buckets, gen_update, "rebalance_update",0,
                        batch_size=20,timeout_secs=self.sdk_timeout,process_concurrency=8,retries=self.sdk_retries,
                        transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level))
        
        for task in tasks:
            self.task.jython_task_manager.get_task_result(task)
        self.sleep(20)
        #=======================================================================
        # for bucket in self.bucket_util.buckets:
        #     current_items = self.bucket_util.get_bucket_current_item_count(self.cluster, bucket)
        #     self.num_items = current_items
        #=======================================================================
        servs_in = [self.cluster.servers[i + self.nodes_init] for i in range(self.nodes_in)]
        #=======================================================================
        # self.bucket_util.verify_stats_all_buckets(self.num_items, timeout=120)
        # self.bucket_util.verify_cluster_stats(self.num_items)
        #=======================================================================
        self.sleep(20)
        
        prev_failover_stats = self.bucket_util.get_failovers_logs(self.cluster.servers[:self.nodes_init], self.bucket_util.buckets)
        prev_vbucket_stats = self.bucket_util.get_vbucket_seqnos(self.cluster.servers[:self.nodes_init], self.bucket_util.buckets)
        
        disk_replica_dataset, disk_active_dataset = self.bucket_util.get_and_compare_active_replica_data_set_all(
            self.cluster.servers[:self.nodes_init], self.bucket_util.buckets, path=None)
        
        self.rest = RestConnection(self.cluster.master)
        self.nodes = self.cluster_util.get_nodes(self.cluster.master)
        chosen = self.cluster_util.pick_nodes(self.cluster.master, howmany=1)
        
        # Mark Node for failover
        success_failed_over = self.rest.fail_over(chosen[0].id, graceful=False)
        # Mark Node for full recovery
        if success_failed_over:
            self.rest.set_recovery_type(otpNode=chosen[0].id, recoveryType="full")
            
        rebalance = self.task.async_rebalance(self.cluster.servers[:self.nodes_init], servs_in, [])
        self.task.jython_task_manager.get_task_result(rebalance)
        self.sleep(60)
        self.cluster.nodes_in_cluster.extend(servs_in)
        #=======================================================================
        # self.bucket_util.verify_stats_all_buckets(self.num_items, timeout=120)
        # self.bucket_util.verify_cluster_stats(self.num_items, check_ep_items_remaining=True)
        #=======================================================================
        self.bucket_util.compare_failovers_logs(prev_failover_stats, self.cluster.servers[:self.nodes_in + self.nodes_init], self.bucket_util.buckets)
        self.sleep(30)
        
        self.bucket_util.data_analysis_active_replica_all(
            disk_active_dataset, disk_replica_dataset,
            self.cluster.servers[:self.nodes_in + self.nodes_init],
            self.bucket_util.buckets, path=None)
        #=======================================================================
        self.bucket_util.verify_unacked_bytes_all_buckets()
        #=======================================================================
        nodes = self.cluster_util.get_nodes_in_cluster(self.cluster.master)
        self.bucket_util.vb_distribution_analysis(
            servers=nodes, buckets=self.bucket_util.buckets,
            num_replicas=self.num_replicas,
            std=std, total_vbuckets=self.vbuckets)

    def rebalance_in_with_failover(self):
        """
        Rebalances  after we do add node and graceful failover

        This test begins by loading a given number of items into the cluster.
        It then adds nodes_in nodes at a time and rebalances that nodes
        into the cluster.
        During the rebalance we perform docs ops(add/remove/update/readd)
        in the cluster( operate with a half of items that were loaded before).
        We then  add a node and do graceful failover followed by rebalance
        Once the cluster is rebalanced we wait for the disk queues to drain,
        then verify that there has been no data loss and sum(curr_items)
        match the curr_items_total.
        Once all nodes have been rebalanced in the test is finished.
        """
        self.transaction_timeout = self.input.param("transaction_timeout", 100)
        self.transaction_commit = self.input.param("transaction_commit", True)
        
        fail_over = self.input.param("fail_over", False)
        gen_update = self.get_doc_generator(0, self.num_items)
        std = self.std_vbucket_dist or 1.0
        tasks = []
        tasks.append(self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             gen_update,"rebalance_update",0,
                                             batch_size=10,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level))
        
        for task in tasks:
            self.task.jython_task_manager.get_task_result(task)
        servs_in = [self.cluster.servers[i + self.nodes_init] for i in range(self.nodes_in)]
        self.sleep(20)
        #=======================================================================
        # for bucket in self.bucket_util.buckets:
        #     current_items = self.bucket_util.get_bucket_current_item_count(self.cluster, bucket)
        #     self.num_items = current_items
        # self.bucket_util.verify_stats_all_buckets(self.num_items, timeout=120)
        # self.bucket_util._wait_for_stats_all_buckets()
        # self.sleep(20)
        #=======================================================================
        prev_failover_stats = self.bucket_util.get_failovers_logs(self.cluster.servers[:self.nodes_init], self.bucket_util.buckets)
        prev_vbucket_stats = self.bucket_util.get_vbucket_seqnos(self.cluster.servers[:self.nodes_init], self.bucket_util.buckets)
        
        disk_replica_dataset, disk_active_dataset = self.bucket_util.get_and_compare_active_replica_data_set_all(
            self.cluster.servers[:self.nodes_init], self.bucket_util.buckets, path=None)
        
        self.rest = RestConnection(self.cluster.master)
        self.nodes = self.cluster_util.get_nodes(self.cluster.master)
        chosen = self.cluster_util.pick_nodes(self.cluster.master, howmany=1)
        
        self.rest = RestConnection(self.cluster.master)
        self.rest.add_node(self.cluster.master.rest_username,
                           self.cluster.master.rest_password,
                           self.cluster.servers[self.nodes_init].ip,
                           self.cluster.servers[self.nodes_init].port)
        # Mark Node for failover
        self.rest.fail_over(chosen[0].id, graceful=fail_over)
        if fail_over:
            self.assertTrue(self.rest.monitorRebalance(stop_if_loop=True),
                            msg="Graceful Failover Failed")
            
        self.nodes = self.rest.node_statuses()
        self.rest.rebalance(otpNodes=[node.id for node in self.nodes],
                            ejectedNodes=[chosen[0].id])
        self.assertTrue(self.rest.monitorRebalance(stop_if_loop=True),
                        msg="Rebalance Failed")
        
        self.sleep(60)
        # Verification
        new_server_list = self.cluster_util.add_remove_servers(
            self.cluster.servers, self.cluster.servers[:self.nodes_init],
            [chosen[0]], [self.cluster.servers[self.nodes_init]])
        self.cluster.nodes_in_cluster = new_server_list
        #=======================================================================
        # self.bucket_util.verify_stats_all_buckets(self.num_items, timeout=120)
        # self.bucket_util.verify_cluster_stats(self.num_items,
        #                                       check_ep_items_remaining=True)
        #=======================================================================
        self.bucket_util.compare_failovers_logs(
            prev_failover_stats, new_server_list, self.bucket_util.buckets)
        self.sleep(30)
        
        self.bucket_util.data_analysis_active_replica_all(
            disk_active_dataset, disk_replica_dataset, new_server_list,
            self.bucket_util.buckets, path=None)
        
        #=======================================================================
        # self.bucket_util.verify_unacked_bytes_all_buckets()
        #=======================================================================
        
        nodes = self.cluster_util.get_nodes_in_cluster(self.cluster.master)
        self.bucket_util.vb_distribution_analysis(
            servers=nodes, buckets=self.bucket_util.buckets,
            num_replicas=self.num_replicas,
            std=std, total_vbuckets=self.vbuckets)

    def rebalance_in_with_compaction_and_ops(self):
        """
        Rebalances nodes into a cluster while doing
        docs ops:create, delete, update

        This test begins by loading a given number of items into the cluster.
        We later run compaction on all buckets and do ops as well
        """
        self.transaction_timeout = self.input.param("transaction_timeout", 100)
        self.transaction_commit = self.input.param("transaction_commit", True)
        
        servs_in = [self.cluster.servers[i + self.nodes_init] for i in range(self.nodes_in)]
        tasks = [self.task.async_rebalance(self.cluster.servers[:self.nodes_init], servs_in, [])]
        for bucket in self.bucket_util.buckets:
            tasks.append(self.task.async_compact_bucket(self.cluster.master, bucket))
        
        if ("update" in self.doc_ops):
                    # 1/2th of data will be updated in each iteration
            tasks.append(self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             self.gen_update,"rebalance_update",0,
                                             batch_size=20,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level))
        
        elif ("create" in self.doc_ops):
                    # 1/2th of initial data will be added in each iteration
            gen_create = self.get_doc_generator(self.num_items * (1+i)/2.0, self.num_items * (1 + i / 2.0))
            tasks.append(self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             gen_create,"create",100,
                                             batch_size=10,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level))
        
        elif ("delete" in self.doc_ops):
                    # 1/(num_servers) of initial data will be removed after each iteration
                    # at the end we should get empty base( or couple items)
            gen_delete = self.get_doc_generator(int(self.num_items * (1-i / (self.num_servers - 1.0))) + 1,
                                                        int(self.num_items * (1-(i-1) / (self.num_servers - 1.0))))
            tasks.append(self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             gen_delete,"rebalance_delete",100,
                                             batch_size=10,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level))
        
        for task in tasks:
            self.task.jython_task_manager.get_task_result(task)
        self.cluster.nodes_in_cluster.extend(servs_in)
        self.sleep(60)
        #=======================================================================
        # for bucket in self.bucket_util.buckets:
        #     current_items = self.bucket_util.get_bucket_current_item_count(self.cluster, bucket)
        #     self.num_items = current_items
        # self.bucket_util.verify_cluster_stats(self.num_items)
        # self.bucket_util.verify_unacked_bytes_all_buckets()
        #=======================================================================

    def rebalance_in_with_ops_batch(self):
        self.transaction_timeout = self.input.param("transaction_timeout", 100)
        self.transaction_commit = self.input.param("transaction_commit", True)
        
        gen_delete = self.get_doc_generator((self.num_items / 2 - 1), self.num_items)
        gen_create = self.get_doc_generator(self.num_items+1, self.num_items*3/2)
        
        servs_in = [self.cluster.servers[i + 1] for i in range(self.nodes_in)]
        rebalance = self.task.async_rebalance(self.cluster.servers[:1], servs_in, [])
        if (self.doc_ops is not None):
            # define which doc's ops will be performed during rebalancing
            # allows multiple of them but one by one
            if ("update" in self.doc_ops):
                self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             self.gen_update,"rebalance_update",0,4294967295,True,
                                             batch_size=20,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level)
        
            if ("create" in self.doc_ops):
                self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             gen_create,"create",0,4294967295,True,
                                             batch_size=20,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level)
        
            if ("delete" in self.doc_ops):
                self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             gen_delete,"rebalance_delete",0,4294967295,True,
                                             batch_size=20,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level)
        
                
        self.task.jython_task_manager.get_task_result(rebalance)
        self.cluster.nodes_in_cluster.extend(servs_in)
        self.sleep(60)
        #=======================================================================
        # for bucket in self.bucket_util.buckets:
        #     current_items = self.bucket_util.get_bucket_current_item_count(self.cluster, bucket)
        #     self.num_items = current_items
        # self.bucket_util._wait_for_stats_all_buckets()
        # self.bucket_util.verify_stats_all_buckets(self.num_items)
        # self.bucket_util.verify_unacked_bytes_all_buckets()
        #=======================================================================

    def rebalance_in_get_random_key(self):
        """
        Rebalances nodes into a cluster during getting random keys.

        This test begins by loading a given number of items into the node.
        Then it creates cluster with self.nodes_init nodes. Then we
        send requests to all nodes in the cluster to get random key values.
        Next step is add nodes_in nodes into cluster and rebalance it.
        During rebalancing we get random keys from all nodes and
        verify that are different every time.
        Once the cluster has been rebalanced we again get random keys from all
        new nodes in the cluster, then we wait for the disk queues to drain,
        and then verify that there has been no data loss, sum(curr_items)
        match the curr_items_total
        """
        self.transaction_timeout = self.input.param("transaction_timeout", 100)
        self.transaction_commit = self.input.param("transaction_commit", True)
        
        servs_in = self.cluster.servers[self.nodes_init:self.nodes_init + self.nodes_in]
        rebalance = self.task.async_rebalance(self.cluster.servers[:1], servs_in, [])
        
        self.sleep(5)
        
        rest_cons = [RestConnection(self.cluster.servers[i]) for i in xrange(self.nodes_init)]
        result = []
        num_iter = 0
        # get random keys for each node during rebalancing
        while rest_cons[0]._rebalance_progress_status() == 'running' and num_iter < 100:
            temp_result = []
            self.log.info("getting random keys for all nodes in cluster....")
            for rest in rest_cons:
                result.append(rest.get_random_key('default'))
                self.sleep(1)
                temp_result.append(rest.get_random_key('default'))

            if tuple(temp_result) == tuple(result):
                self.log.exception("random keys are not changed")
            else:
                result = temp_result
            num_iter += 1

        self.task.jython_task_manager.get_task_result(rebalance)
        self.cluster.nodes_in_cluster.extend(servs_in)
        self.sleep(60)
        #=======================================================================
        # 
        # for bucket in self.bucket_util.buckets:
        #     current_items = self.bucket_util.get_bucket_current_item_count(self.cluster, bucket)
        #     self.num_items = current_items
        #=======================================================================
        # get random keys for new added nodes
        rest_cons = [RestConnection(self.cluster.servers[i]) for i in xrange(self.nodes_init + self.nodes_in)]
        for rest in rest_cons:
            result = rest.get_random_key('default')
        #=======================================================================
        # self.bucket_util.verify_cluster_stats(self.num_items)
        # self.bucket_util.verify_unacked_bytes_all_buckets()
        #=======================================================================

    def incremental_rebalance_in_with_ops(self):
        """
        Rebalances nodes into a cluster while doing mutations.

        This test begins by loading a given number of items into the cluster.
        Then adds two nodes at a time & rebalances that node into the cluster.
        During the rebalance we update(all of the items in the cluster)/
        delete(num_items/(num_servers-1) in each iteration)/
        create(a half of initial items in each iteration).
        Once the cluster has been rebalanced we wait for the disk queues to
        drain, and then verify that there has been no data loss,
        sum(curr_items) match the curr_items_total.
        Once all nodes have been rebalanced in the test is finished.
        """
        self.transaction_timeout = self.input.param("transaction_timeout", 100)
        self.transaction_commit = self.input.param("transaction_commit", True)
        
        num_of_items = self.num_items
        for i in range(1, self.num_servers, 2):
            tasks = [self.task.async_rebalance(self.cluster.servers[:i], self.cluster.servers[i:i + 2], [])]
            if self.doc_ops is not None:
                # define which doc's operation will be performed during rebalancing
                # only one type of ops can be passed
                self.bucket_util.buckets
               
                if ("update" in self.doc_ops):
                        # 1/2th of data will be updated in each iteration
                    tasks.append(self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             self.gen_update,"rebalance_update",0,
                                             batch_size=20,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level))
        
                elif ("create" in self.doc_ops):
                        # 1/2th of initial data will be added in each iteration
                    tem_num_items = int(self.num_items * (1 + i / 2.0))
                    gen_create = self.get_doc_generator(num_of_items,
                                                            tem_num_items)
                    num_of_items = tem_num_items
                    tasks.append(self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             gen_create,"create",0,
                                             batch_size=10,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level))
        
                elif ("delete" in self.doc_ops):
                        # 1/(num_servers) of initial data will be removed after each iteration
                        # at the end we should get empty base( or couple items)
                    tem_del_start_num = int(self.num_items * (1 - i / (self.num_servers - 1.0))) + 1
                    tem_del_end_num = int(self.num_items * (1 - (i - 1) / (self.num_servers - 1.0)))
                    gen_delete = self.get_doc_generator(tem_del_start_num,
                                                            tem_del_end_num)
                    self.num_items -= (tem_del_end_num - tem_del_start_num + 1)
                    tasks.append(self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             gen_delete,"rebalance_delete",0,
                                             batch_size=10,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level))
        
            for task in tasks:
                self.task.jython_task_manager.get_task_result(task)
            self.cluster.nodes_in_cluster.extend(self.cluster.servers[i:i + 2])
            
            self.sleep(60, "Wait for cluster to be ready after rebalance")
        #=======================================================================
        #     for bucket in self.bucket_util.buckets:
        #         current_items = self.bucket_util.get_bucket_current_item_count(self.cluster, bucket)
        #         self.num_items = current_items
        #     self.bucket_util.verify_cluster_stats(num_of_items)
        # self.bucket_util.verify_unacked_bytes_all_buckets()
        #=======================================================================

    def rebalance_in_with_queries(self):
        """
        Rebalances nodes into a cluster  during view queries.

        This test begins by loading a given number of items into the cluster.
        It creates num_views as development/production views with default
        map view funcs(is_dev_ddoc = True by default).
        It then adds nodes_in nodes at a time and rebalances that node into
        the cluster.
        During the rebalancing we perform view queries for all views and verify
        the expected number of docs for them. Perform the same view queries
        after cluster has been completed. Then we wait for the disk queues to
        drain, and then verify that there has been no data loss,
        sum(curr_items) match the curr_items_total.
        Once successful view queries the test is finished.

        Added reproducer for MB-6683
        """
        self.transaction_timeout = self.input.param("transaction_timeout", 500)
        self.transaction_commit = self.input.param("transaction_commit", True)
        
        self.bucket_util._wait_for_stats_all_buckets()

        num_views = self.input.param("num_views", 5)
        is_dev_ddoc = self.input.param("is_dev_ddoc", True)
        reproducer = self.input.param("reproducer", False)
        num_tries = self.input.param("num_tries", 10)
        iterations_to_try = (1, num_tries)[reproducer]
        ddoc_name = "ddoc1"
        prefix = ("", "dev_")[is_dev_ddoc]

        query = {}
        query["connectionTimeout"] = 60000
        query["full_set"] = "true"
        
        task = self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             self.gen_load,"create",0,
                                             batch_size=10,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level)
        self.task.jython_task_manager.get_task_result(task)
        self.sleep(60 , "This task is completed")
        
        views = []
        tasks = []
        for bucket in self.bucket_util.buckets:
            temp = self.bucket_util.make_default_views(
                self.default_view, num_views, is_dev_ddoc,
                different_map=reproducer)
            temp_tasks = self.bucket_util.async_create_views(self.cluster.master, prefix + ddoc_name, temp, bucket)
            views += temp
            tasks += temp_tasks

        timeout = None
        if self.active_resident_threshold == 0:
            timeout = max(self.wait_timeout * 4, len(self.bucket_util.buckets) * self.wait_timeout * self.num_items / 50000)
            
        
            
        for task in tasks:
            self.task.jython_task_manager.get_task_result(task)
            
        for bucket in self.bucket_util.buckets:
            for view in views:
                # run queries to create indexes
                self.bucket_util.query_view(self.cluster.master, prefix + ddoc_name, view.name, query)

        active_tasks = self.cluster_util.async_monitor_active_task(
            self.cluster.servers[:self.nodes_init], "indexer",
            "_design/" + prefix + ddoc_name, wait_task=False)
        for active_task in active_tasks:
            result = self.task.jython_task_manager.get_task_result(active_task)
            self.assertTrue(result)

        expected_rows = self.num_items
        if self.max_verify:
            expected_rows = self.max_verify
            query["limit"] = expected_rows
        query["stale"] = "false"

        for bucket in self.bucket_util.buckets:
            self.bucket_util.perform_verify_queries(
                num_views, prefix, ddoc_name, self.default_view_name,
                query, bucket=bucket, wait_time=timeout,
                expected_rows=expected_rows)
        for i in xrange(iterations_to_try):
            servs_in = self.cluster.servers[self.nodes_init:self.nodes_init + self.nodes_in]
            rebalance = self.task.async_rebalance([self.cluster.master], servs_in, [])
            self.sleep(self.wait_timeout / 5)

            # See that the result of view queries are same as
            # the expected during the test
            for bucket in self.bucket_util.buckets:
                self.bucket_util.perform_verify_queries(
                    num_views, prefix, ddoc_name, self.default_view_name,
                    query, bucket=bucket, wait_time=timeout,
                    expected_rows=expected_rows)

            self.task.jython_task_manager.get_task_result(rebalance)
            self.cluster.nodes_in_cluster.extend(servs_in)
            self.sleep(60,"Verifying view queries")
            # verify view queries results after rebalancing
            for bucket in self.bucket_util.buckets:
                self.bucket_util.perform_verify_queries(num_views, prefix, ddoc_name, self.default_view_name,
                                                        query, bucket=bucket, wait_time=timeout,
                                                        expected_rows=expected_rows)

            # self.bucket_util.verify_cluster_stats(self.num_items)
            self.sleep(120,"Value of reproducer is defined in the parameters")
            if reproducer:
                rebalance = self.task.async_rebalance(self.cluster.servers, [], servs_in)
                self.task.jython_task_manager.get_task_result(rebalance)
                self.cluster.nodes_in_cluster = list(set(self.cluster.nodes_in_cluster) - set(servs_in))
                self.sleep(self.wait_timeout)
            self.sleep(60)
        #=======================================================================
        # self.bucket_util.verify_unacked_bytes_all_buckets()
        #=======================================================================

    def incremental_rebalance_in_with_queries(self):
        """
        Rebalances nodes into a cluster incremental during view queries.

        This test begins by loading a given number of items into the cluster.
        It creates num_views as development/production view with default
        map view funcs(is_dev_ddoc = True by default).
        Then adds two nodes at a time & rebalances that node into the cluster.
        During the rebalancing we perform view queries for all views and verify
        the expected number of docs for them. Perform the same view queries
        after cluster has been completed. Then we wait for the disk queues to
        drain, and then verify that there has been no data loss,
        sum(curr_items) match the curr_items_total.
        Once all nodes have been rebalanced in the test is finished.
        """

        num_views = self.input.param("num_views", 5)
        is_dev_ddoc = self.input.param("is_dev_ddoc", False)
        views = self.bucket_util.make_default_views(self.default_view, num_views, is_dev_ddoc)
        ddoc_name = "ddoc1"
        prefix = ("", "dev_")[is_dev_ddoc]
        # increase timeout for big data
        timeout = max(self.wait_timeout * 4, self.wait_timeout * self.num_items / 25000)
        query = {}
        query["connectionTimeout"] = 60000
        query["full_set"] = "true"
        tasks = []
        tasks = self.bucket_util.async_create_views(self.cluster.master, prefix + ddoc_name, views, 'default')
        for task in tasks:
            self.task_manager.get_task_result(task)
        for view in views:
            # run queries to create indexes
            self.bucket_util.query_view(self.cluster.master, prefix + ddoc_name, view.name, query)

        active_tasks = self.cluster_util.async_monitor_active_task(
            self.cluster.master, "indexer", "_design/" + prefix + ddoc_name,
            wait_task=False)
        for active_task in active_tasks:
            result = active_task.check()
            self.assertTrue(result)

        expected_rows = None
        if self.max_verify:
            expected_rows = self.max_verify
            query["limit"] = expected_rows
        query["stale"] = "false"

        self.bucket_util.perform_verify_queries(num_views, prefix, ddoc_name, self.default_view_name,
                                                query, wait_time=timeout, expected_rows=expected_rows)
        query["stale"] = "update_after"
        for i in range(1, self.num_servers, 2):
            rebalance = self.task.async_rebalance(self.cluster.servers[:i], self.cluster.servers[i:i + 2], [])
            self.sleep(self.wait_timeout / 5)
            # see that the result of view queries are the same as expected during the test
            self.bucket_util.perform_verify_queries(num_views, prefix, ddoc_name, self.default_view_name,
                                                    query, wait_time=timeout, expected_rows=expected_rows)
            # verify view queries results after rebalancing
            self.task.jython_task_manager.get_task_result(rebalance)
            self.cluster.nodes_in_cluster.extend(self.cluster.servers[i:i + 2])
            self.sleep(60)
            self.bucket_util.perform_verify_queries(num_views, prefix, ddoc_name, self.default_view_name,
                                                    query, wait_time=timeout, expected_rows=expected_rows)
        #=======================================================================
        #     self.bucket_util.verify_cluster_stats(self.num_items)
        # self.bucket_util.verify_unacked_bytes_all_buckets()
        #=======================================================================

    def rebalance_in_with_warming_up(self):
        """
        Rebalances nodes into a cluster when one node is warming up.

        This test begins by loading a given number of items into the node.
        Then it creates cluster with self.nodes_init nodes. Next steps are:
        stop the latest node in servs_init list(if list size==1, master node/
        cluster will be stopped), wait 20 sec and start the stopped node.
        Without waiting for the node to start up completely, rebalance in
        servs_in servers. Expect that rebalance is failed. Wait for warmup
        completed and strart rebalance with the same configuration.
        Once the cluster has been rebalanced we wait for the disk queues
        to drain, and then verify that there has been no data loss,
        sum(curr_items) match the curr_items_total.
        """

        servs_in = self.cluster.servers[self.nodes_init:self.nodes_init + self.nodes_in]
        servs_init = self.cluster.servers[:self.nodes_init]
        warmup_node = servs_init[-1]
        shell = RemoteMachineShellConnection(warmup_node)
        shell.stop_couchbase()
        self.sleep(20)
        shell.start_couchbase()
        shell.disconnect()
        try:
            rebalance = self.task.async_rebalance(servs_init, servs_in, [])
            self.task.jython_task_manager.get_task_result(rebalance)
            self.cluster.nodes_in_cluster.extend(servs_in)
        except RebalanceFailedException:
            self.log.info("rebalance was failed as expected")
            self.assertTrue(self.cluster_util._wait_warmup_completed(
                self, [warmup_node], 'default',
                wait_time=self.wait_timeout * 10))

            self.log.info("second attempt to rebalance")
            rebalance = self.task.async_rebalance(servs_init + servs_in, [], [])
            self.cluster.nodes_in_cluster.extend(servs_in)
            self.task.jython_task_manager.get_task_result(rebalance)
        self.sleep(60)
        #=======================================================================
        # self.bucket_util.verify_cluster_stats(self.num_items)
        # self.bucket_util.verify_unacked_bytes_all_buckets()
        #=======================================================================

    def rebalance_in_with_ddoc_compaction(self):
        """
        Rebalances nodes into a cluster during ddoc compaction.

        This test begins by loading a given number of items into the cluster.
        It creates num_views as development/production view with default
        map view funcs(is_dev_ddoc = True by default). Then we disabled
        compaction for ddoc. While we don't reach expected fragmentation for
        ddoc we update docs and perform view queries. We rebalance in  nodes_in
        nodes and start compation when fragmentation was reached
        fragmentation_value. During the rebalancing we wait while compaction
        will be completed. After rebalancing and compaction we wait for the
        disk queues to drain, and then verify that there has been no data loss,
        sum(curr_items) match the curr_items_total.
        """

        num_views = self.input.param("num_views", 5)
        fragmentation_value = self.input.param("fragmentation_value", 80)
        # now dev_ indexes are not auto-updated, doesn't work with dev view
        is_dev_ddoc = False
        views = self.bucket_util.make_default_views(self.default_view, num_views, is_dev_ddoc)
        ddoc_name = "ddoc1"
        prefix = ("", "dev_")[is_dev_ddoc]

        query = {}
        query["connectionTimeout"] = 60000
        query["full_set"] = "true"

        expected_rows = None
        if self.max_verify:
            expected_rows = self.max_verify
            query["limit"] = expected_rows

        tasks = []
        tasks = self.bucket_util.async_create_views(
            self.cluster.master, prefix + ddoc_name, views, 'default')
        for task in tasks:
            self.task_manager.get_task_result(task)
        self.bucket_util.disable_compaction()
        fragmentation_monitor = self.cluster.async_monitor_view_fragmentation(
            self.cluster.master, prefix + ddoc_name, fragmentation_value,
            'default')
        end_time = time.time() + self.wait_timeout * 30
        # generate load until fragmentation reached
        while fragmentation_monitor.state != "FINISHED" and end_time > time.time():
            # update docs to create fragmentation
            self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             self.gen_update,"rebalance_update",0,
                                             batch_size=20,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level)
        
            for view in views:
                # run queries to create indexes
                self.cluster.query_view(self.cluster.master, prefix + ddoc_name, view.name, query)
        if end_time < time.time() and fragmentation_monitor.state != "FINISHED":
            self.fail("impossible to reach compaction value {0} after {1} sec".
                      format(fragmentation_value, (self.wait_timeout * 30)))

        fragmentation_monitor.result()

        for _ in xrange(3):
            active_tasks = self.cluster.async_monitor_active_task(
                self.cluster.master, "indexer",
                "_design/" + prefix + ddoc_name, wait_task=False)
            for active_task in active_tasks:
                result = active_task.result()
                self.assertTrue(result)
            self.sleep(2)

        query["stale"] = "false"

        self.bucket_util.perform_verify_queries(
            num_views, prefix, ddoc_name, self.default_view_name, query,
            wait_time=self.wait_timeout*3, expected_rows=expected_rows)

        compaction_task = self.cluster.async_compact_view(
            self.cluster.master, prefix + ddoc_name, 'default',
            with_rebalance=True)
        servs_in = self.cluster.servers[1:self.nodes_in + 1]
        rebalance = self.task.async_rebalance([self.cluster.master], servs_in, [])
        result = compaction_task.result(self.wait_timeout * 10)
        self.assertTrue(result)
        self.task.jython_task_manager.get_task_result(rebalance)
        self.cluster.nodes_in_cluster.extend(servs_in)
        #=======================================================================
        # self.bucket_util.verify_cluster_stats(self.num_items)
        # self.bucket_util.verify_unacked_bytes_all_buckets()
        #=======================================================================

    def incremental_rebalance_in_with_mutation_and_deletion(self):
        """
        Rebalances nodes into a cluster while doing mutations and deletions.

        This test begins by loading a given number of items into the cluster.
        It then adds one node at a time & rebalances the node into the cluster.
        During the rebalance we update half of the items in the cluster and
        delete the other half. Once the cluster has been rebalanced we recreate
        the deleted items, wait for the disk queues to drain, and then verify
        that there has been no data loss.
        sum(curr_items) match the curr_items_total.
        Once all nodes have been rebalanced in the test is finished.
        """
        self.transaction_timeout = self.input.param("transaction_timeout", 100)
        self.transaction_commit = self.input.param("transaction_commit", True)
        gen_delete = self.get_doc_generator(self.num_items / 2,
                                            self.num_items)

        for i in range(self.num_servers)[1:]:
            rebalance = self.task.async_rebalance(self.cluster.servers[:i], [self.cluster.servers[i]], [])
            self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             self.gen_update,"rebalance_update",0,
                                             batch_size=20,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level)
        
            self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             gen_delete,"rebalance_delete",0,
                                             batch_size=20,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level)
        
            self.task.jython_task_manager.get_task_result(rebalance)
            self.cluster.nodes_in_cluster.extend([self.cluster.servers[i]])
            self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             gen_delete,"create",0,
                                             batch_size=20,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level)
        
        #=======================================================================
        #     self.bucket_util.verify_cluster_stats(self.num_items)
        # self.bucket_util.verify_unacked_bytes_all_buckets()
        #=======================================================================

    def incremental_rebalance_in_with_mutation_and_expiration(self):
        """
        Rebalances nodes into a cluster while doing mutations and expirations.

        This test begins by loading a given number of items into the cluster.
        It then adds one node at a time & rebalances the node into the cluster.
        During the rebalance we update all items in the cluster. Half of the
        items updated are also given an expiration time of 5 seconds.
        Once the cluster has been rebalanced we recreate the expired items,
        wait for the disk queues to drain, and then verify that there has been
        no data loss, sum(curr_items) match the curr_items_total.
        Once all nodes have been rebalanced in the test is finished.
        """

        gen_2 = self.get_doc_generator(self.num_items / 2,
                                       self.num_items)
        for i in range(self.num_servers)[1:]:
            rebalance = self.task.async_rebalance(self.cluster.servers[:i],
                                                  [self.cluster.servers[i]], [])
            self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             self.gen_update,"rebalance_update",0,
                                             batch_size=20,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level)
        
            self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             gen_2,"rebalance_update",5,
                                             batch_size=20,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level)
        
            self.sleep(5)
            self.task.jython_task_manager.get_task_result(rebalance)
            self.task.async_load_gen_docs_atomicity(self.cluster, self.bucket_util.buckets,
                                             gen_2,"create",0,
                                             batch_size=20,timeout_secs=self.sdk_timeout,process_concurrency=8,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,durability=self.durability_level)
        self.sleep(60)
        #=======================================================================
        #     self.bucket_util.verify_cluster_stats(self.num_items)
        # self.bucket_util.verify_unacked_bytes_all_buckets()
        #=======================================================================

    def test_rebalance_in_with_cluster_ramquota_change(self):
        '''
        test changes ram quota during rebalance.
        http://www.couchbase.com/issues/browse/CBQE-1649
        '''
        rebalance = self.task.async_rebalance(
            self.cluster.servers[:self.nodes_init],
            self.cluster.servers[self.nodes_init:self.nodes_init + self.nodes_in],
            [])
        self.sleep(10, "Wait for rebalance have some progress")
        remote = RemoteMachineShellConnection(self.cluster.master)
        cli_command = "setting-cluster"
        options = "--cluster-ramsize=%s" % (3000)
        output, error = remote.execute_couchbase_cli(
            cli_command=cli_command, options=options, cluster_host="localhost",
            user=self.cluster.master.rest_username,
            password=self.cluster.master.rest_password)
        self.assertTrue('\n'.join(output).find('SUCCESS') != -1,
                        'RAM wasn\'t chnged')
        self.task.jython_task_manager.get_task_result(rebalance)
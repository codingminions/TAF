from couchbase_helper.documentgenerator import DocumentGenerator
from membase.api.rest_client import RestConnection
from membase.helper.rebalance_helper import RebalanceHelper
from Atomicity.rebalance_new.rebalance_base import RebalanceBaseTest
from java.util.concurrent import ExecutionException

class RebalanceInOutTests(RebalanceBaseTest):

    def setUp(self):
        super(RebalanceInOutTests, self).setUp()
        self.transaction_timeout = self.input.param("transaction_timeout", 300)
        self.transaction_commit = self.input.param("transaction_commit", True)
        self.op_type = self.input.param("op_type", 'create')
        self.def_bucket= self.bucket_util.get_all_buckets()
        
    def tearDown(self):
        super(RebalanceInOutTests, self).tearDown()
        
    

    def test_rebalance_in_out_after_mutation(self):
        """
        Rebalances nodes out and in of the cluster while doing mutations.
        Use different nodes_in and nodes_out params to have uneven add and deletion. Use 'zone'
        param to have nodes divided into server groups by having zone > 1.

        This test begins by loading a given number of items into the cluster. It then
        removes one node, rebalances that node out the cluster, and then rebalances it back
        in. During the rebalancing we update all of the items in the cluster. Once the
        node has been removed and added back we  wait for the disk queues to drain, and
        then verify that there has been no data loss, sum(curr_items) match the curr_items_total.
        We then remove and add back two nodes at a time and so on until we have reached the point
        where we are adding back and removing at least half of the nodes.
        """
        # Shuffle the nodes if zone > 1 is specified.
        if self.zone > 1:
            self.shuffle_nodes_between_zones_and_rebalance()
        gen = self.get_doc_generator(0, self.num_items)
        task = self.task.async_load_gen_docs_atomicity(self.cluster, self.def_bucket,
                                             gen, self.op_type , exp=0,
                                             batch_size=10,
                                             process_concurrency=8,
                                             replicate_to=self.replicate_to,
                                             persist_to=self.persist_to, timeout_secs=self.sdk_timeout,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,
                                             durability=self.durability_level, sync=self.sync)
        servs_in = self.cluster.servers[self.nodes_init:self.nodes_init + self.nodes_in]
        servs_out = self.cluster.servers[self.nodes_init - self.nodes_out:self.nodes_init]
        result_nodes = list(set(self.cluster.servers[:self.nodes_init] + servs_in) - set(servs_out)) 
        try:       
            self.task_manager.get_task_result(task)
        except ExecutionException:
                pass

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
        self.bucket_util.vb_distribution_analysis(servers=nodes, std=1.0, total_vbuckets=self.vbuckets)

    def test_rebalance_in_out_with_failover_addback_recovery(self):
        """
        Rebalances nodes out and in with failover and full/delta recovery add back of a node
        Use different nodes_in and nodes_out params to have uneven add and deletion. Use 'zone'
        param to have nodes divided into server groups by having zone > 1.

        This test begins by loading a given number of items into the cluster. It then
        removes one node, rebalances that node out the cluster, and then rebalances it back
        in. During the rebalancing we update all of the items in the cluster. Once the
        node has been removed and added back we  wait for the disk queues to drain, and
        then verify that there has been no data loss, sum(curr_items) match the curr_items_total.
        We then remove and add back two nodes at a time and so on until we have reached the point
        where we are adding back and removing at least half of the nodes.
        """
        recovery_type = self.input.param("recoveryType", "full")
        gen = self.get_doc_generator(0, self.num_items)
        task = self.task.async_load_gen_docs_atomicity(self.cluster, self.def_bucket,
                                             self.gen_update, "rebalance_update" , exp=0,
                                             batch_size=10,
                                             process_concurrency=8,
                                             replicate_to=self.replicate_to,
                                             persist_to=self.persist_to, timeout_secs=self.sdk_timeout,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit,
                                             durability=self.durability_level, sync=self.sync)
        servs_in = self.cluster.servers[self.nodes_init:self.nodes_init + self.nodes_in]
        servs_out = self.cluster.servers[self.nodes_init - self.nodes_out:self.nodes_init]
        try:
            self.task_manager.get_task_result(task)
        except ExecutionException:
                pass
#         self.bucket_util.verify_stats_all_buckets(self.num_items, timeout=120)
#         self.bucket_util._wait_for_stats_all_buckets()
        self.sleep(120)
        prev_vbucket_stats = self.bucket_util.get_vbucket_seqnos(self.cluster.servers[:self.nodes_init], self.bucket_util.buckets)
        prev_failover_stats = self.bucket_util.get_failovers_logs(self.cluster.servers[:self.nodes_init], self.bucket_util.buckets)
        disk_replica_dataset, disk_active_dataset = self.bucket_util.get_and_compare_active_replica_data_set_all(
            self.cluster.servers[:self.nodes_init], self.bucket_util.buckets, path=None)
        self.bucket_util.compare_vbucketseq_failoverlogs(prev_vbucket_stats, prev_failover_stats)
        self.rest = RestConnection(self.cluster.master)
        self.nodes = self.cluster.nodes_in_cluster
        result_nodes = list(set(self.cluster.servers[:self.nodes_init] + servs_in) - set(servs_out))
        for node in servs_in:
            self.rest.add_node(self.cluster.master.rest_username, self.cluster.master.rest_password, node.ip, node.port)
        chosen = RebalanceHelper.pick_nodes(self.cluster.master, howmany=1)
        # Mark Node for failover
        self.sleep(30)
        success_failed_over = self.rest.fail_over(chosen[0].id, graceful=False)
        # Mark Node for full recovery
        if success_failed_over:
            self.rest.set_recovery_type(otpNode=chosen[0].id, recoveryType=recovery_type)
        self.sleep(30)
        try:
            self.shuffle_nodes_between_zones_and_rebalance(servs_out)
        except Exception, e:
            if "deltaRecoveryNotPossible" not in e.__str__():
                self.fail("Rebalance did not fail. Rebalance has to fail since no delta recovery should be possible"
                          " while adding nodes too")

    def test_rebalance_in_out_with_failover(self):
        """
        Rebalances nodes out and in with failover
        Use different nodes_in and nodes_out params to have uneven add and deletion. Use 'zone'
        param to have nodes divided into server groups by having zone > 1.

        This test begins by loading a given number of items into the cluster. It then
        removes one node, rebalances that node out the cluster, and then rebalances it back
        in. During the rebalancing we update all of the items in the cluster. Once the
        node has been removed and added back we  wait for the disk queues to drain, and
        then verify that there has been no data loss, sum(curr_items) match the curr_items_total.
        We then remove and add back two nodes at a time and so on until we have reached the point
        where we are adding back and removing at least half of the nodes.
        """
        fail_over = self.input.param("fail_over", False)
        gen = self.get_doc_generator(0, self.num_items)
        task = self.task.async_load_gen_docs_atomicity(self.cluster, self.def_bucket,
                                             self.gen_update, "rebalance_update" , exp=0,
                                             batch_size=10,
                                             process_concurrency=8,
                                             replicate_to=self.replicate_to,
                                             persist_to=self.persist_to, timeout_secs=self.sdk_timeout,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit
                                             ,durability=self.durability_level, sync=self.sync)
        servs_in = self.cluster.servers[self.nodes_init:self.nodes_init + self.nodes_in]
        servs_out = self.cluster.servers[self.nodes_init - self.nodes_out:self.nodes_init]
        try:
            self.task_manager.get_task_result(task)
        except ExecutionException:
                pass
#         self.bucket_util.verify_stats_all_buckets(self.num_items, timeout=120)
#         self.bucket_util._wait_for_stats_all_buckets()
        self.sleep(100)
        prev_vbucket_stats = self.bucket_util.get_vbucket_seqnos(self.cluster.servers[:self.nodes_init], self.bucket_util.buckets)
        prev_failover_stats = self.bucket_util.get_failovers_logs(self.cluster.servers[:self.nodes_init], self.bucket_util.buckets)
        disk_replica_dataset, disk_active_dataset = self.bucket_util.get_and_compare_active_replica_data_set_all(
            self.cluster.servers[:self.nodes_init], self.bucket_util.buckets, path=None)
        self.bucket_util.compare_vbucketseq_failoverlogs(prev_vbucket_stats, prev_failover_stats)
        self.rest = RestConnection(self.cluster.master)
        chosen = RebalanceHelper.pick_nodes(self.cluster.master, howmany=1)
        result_nodes = list(set(self.cluster.servers[:self.nodes_init] + servs_in) - set(servs_out))
        result_nodes = [node for node in result_nodes if node.ip != chosen[0].ip]
        for node in servs_in:
            self.rest.add_node(self.cluster.master.rest_username, self.cluster.master.rest_password, node.ip, node.port)
        # Mark Node for failover
        self.rest.fail_over(chosen[0].id, graceful=fail_over)
        self.shuffle_nodes_between_zones_and_rebalance(servs_out)
        self.cluster.nodes_in_cluster = result_nodes
        self.sleep(20)
#         self.bucket_util.verify_cluster_stats(self.num_items, check_ep_items_remaining=True)
        self.bucket_util.compare_failovers_logs(prev_failover_stats, result_nodes, self.bucket_util.buckets)
        self.sleep(30)
        self.bucket_util.data_analysis_active_replica_all(disk_active_dataset, disk_replica_dataset, result_nodes, self.bucket_util.buckets,
                                              path=None)
        self.bucket_util.verify_unacked_bytes_all_buckets()
        nodes = self.cluster.nodes_in_cluster
        #self.bucket_util.vb_distribution_analysis(servers=nodes, std=1.0, total_vbuckets=self.vbuckets)

    def test_incremental_rebalance_in_out_with_mutation(self):
        """
        Rebalances nodes out and in of the cluster while doing mutations.
        Use 'zone' param to have nodes divided into server groups by having zone > 1.

        This test begins by loading a given number of items into the cluster. It then
        removes one node, rebalances that node out the cluster, and then rebalances it back
        in. During the rebalancing we update all of the items in the cluster. Once the
        node has been removed and added back we  wait for the disk queues to drain, and
        then verify that there has been no data loss, sum(curr_items) match the curr_items_total.
        We then remove and add back two nodes at a time and so on until we have reached the point
        where we are adding back and removing at least half of the nodes.
        """
        self.add_remove_servers_and_rebalance(self.cluster.servers[self.nodes_init:self.num_servers], [])
        gen = self.get_doc_generator(0, self.num_items)
        batch_size = 50
        for i in reversed(range(self.num_servers)[self.num_servers / 2:]):
            task = self.task.async_load_gen_docs_atomicity(self.cluster, self.def_bucket,
                                             self.gen_update, "rebalance_update" , exp=0,
                                             batch_size=10,
                                             process_concurrency=8,
                                             replicate_to=self.replicate_to,
                                             persist_to=self.persist_to, timeout_secs=self.sdk_timeout,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit
                                             ,durability=self.durability_level, sync=self.sync)
            self.add_remove_servers_and_rebalance([], self.cluster.servers[i:self.num_servers])
            self.sleep(10)
            try:
                self.task_manager.get_task_result(task)
            except ExecutionException:
                pass
            task = self.task.async_load_gen_docs_atomicity(self.cluster, self.def_bucket,
                                             gen, "rebalance_update" , exp=0,
                                             batch_size=10,
                                             process_concurrency=8,
                                             replicate_to=self.replicate_to,
                                             persist_to=self.persist_to, timeout_secs=self.sdk_timeout,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit
                                             ,durability=self.durability_level, sync=self.sync)
            self.add_remove_servers_and_rebalance(self.cluster.servers[i:self.num_servers], [])
            try:
                self.task_manager.get_task_result(task)
            except ExecutionException:
                pass
            self.sleep(10)
        self.bucket_util.verify_unacked_bytes_all_buckets()

    def test_incremental_rebalance_in_out_with_mutation_and_compaction(self):
        """
        Rebalances nodes out and in of the cluster while doing mutations and compaction.
        Use 'zone' param to have nodes divided into server groups by having zone > 1.

        This test begins by loading a given number of items into the cluster. It then
        removes one node, rebalances that node out the cluster, and then rebalances it back
        in. During the rebalancing we update all of the items in the cluster. Once the
        node has been removed and added back we  wait for the disk queues to drain, and
        then verify that there has been no data loss, sum(curr_items) match the curr_items_total.
        We then remove and add back two nodes at a time and so on until we have reached the point
        where we are adding back and removing at least half of the nodes.
        """
        self.add_remove_servers_and_rebalance(self.cluster.servers[self.nodes_init:self.num_servers], [])
        gen = self.get_doc_generator(0, self.num_items)
        task = self.task.async_load_gen_docs_atomicity(self.cluster, self.def_bucket,
                                             gen, "create" , exp=0,
                                             batch_size=10,
                                             process_concurrency=8,
                                             replicate_to=self.replicate_to,
                                             persist_to=self.persist_to, timeout_secs=self.sdk_timeout,
                                             retries=self.sdk_retries,update_count=self.update_count, transaction_timeout=self.transaction_timeout, 
                                             commit=self.transaction_commit,durability=self.durability_level, sync=self.sync)
        self.task.jython_task_manager.get_task_result(task)
        for i in reversed(range(self.num_servers)[self.num_servers / 2:]):
            task = self.task.async_load_gen_docs_atomicity(self.cluster, self.def_bucket,
                                             gen, "rebalance_only_update" , exp=0,
                                             batch_size=10,
                                             process_concurrency=8,
                                             replicate_to=self.replicate_to,
                                             persist_to=self.persist_to, timeout_secs=self.sdk_timeout,
                                             retries=self.sdk_retries,update_count=self.update_count, transaction_timeout=self.transaction_timeout, 
                                             commit=self.transaction_commit,durability=self.durability_level, sync=self.sync)
             
            compact_tasks = []
            for bucket in self.bucket_util.buckets:
                compact_tasks.append(self.task.async_compact_bucket(self.cluster.master, bucket))
                break
            self.add_remove_servers_and_rebalance([], self.cluster.servers[i:self.num_servers])
            self.task.jython_task_manager.get_task_result(task)
            
            for task in compact_tasks:
                self.task.jython_task_manager.get_task_result(task)
                
                
            task = self.task.async_load_gen_docs_atomicity(self.cluster, self.def_bucket,
                                             gen, "rebalance_only_update" , exp=0,
                                             batch_size=10,
                                             process_concurrency=8,
                                             replicate_to=self.replicate_to,
                                             persist_to=self.persist_to, timeout_secs=self.sdk_timeout,
                                             retries=self.sdk_retries,update_count=self.update_count, transaction_timeout=self.transaction_timeout, 
                                             commit=self.transaction_commit,durability=self.durability_level, sync=self.sync)
            self.add_remove_servers_and_rebalance(self.cluster.servers[i:self.num_servers], [])
            try:
                self.task_manager.get_task_result(task)
            except ExecutionException:
                pass
            self.sleep(20)
#             self.bucket_util.verify_cluster_stats(self.num_items)
        self.bucket_util.verify_unacked_bytes_all_buckets()


    def test_incremental_rebalance_out_in_with_mutation(self):
        """
        Rebalances nodes in and out of the cluster while doing mutations.
        Use 'zone' param to have nodes divided into server groups by having zone > 1.

        This test begins by loading a initial number of nodes into the cluster.
        It then adds one node, rebalances that node into the cluster,
        and then rebalances it back out. During the rebalancing we update all  of
        the items in the cluster. Once the nodes have been removed and added back we
        wait for the disk queues to drain, and then verify that there has been no data loss,
        sum(curr_items) match the curr_items_total.
        We then add and remove back two nodes at a time and so on until we have reached
        the point where we are adding back and removing at least half of the nodes.
        """
        init_num_nodes = self.input.param("init_num_nodes", 1)
        #self.add_remove_servers_and_rebalance(self.cluster.servers[1:init_num_nodes], [])
        gen = self.get_doc_generator(0, self.num_items)
        for i in range(self.num_servers):
            task = self.task.async_load_gen_docs_atomicity(self.cluster, self.def_bucket,
                                             gen, "create" , exp=0,
                                             batch_size=10,
                                             process_concurrency=8,
                                             replicate_to=self.replicate_to,
                                             persist_to=self.persist_to, timeout_secs=self.sdk_timeout,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit
                                             ,durability=self.durability_level, sync=self.sync)
            self.add_remove_servers_and_rebalance(self.cluster.servers[init_num_nodes:init_num_nodes + i + 1], [])
            self.sleep(10)
            self.add_remove_servers_and_rebalance([], self.cluster.servers[init_num_nodes:init_num_nodes + i + 1])
            try:
                self.task_manager.get_task_result(task)
            except ExecutionException:
                pass
            self.sleep(20)
#             self.bucket_util.verify_cluster_stats(self.num_items)
        self.bucket_util.verify_unacked_bytes_all_buckets()

    def test_incremental_rebalance_in_out_with_mutation_and_deletion(self):
        """
        Rebalances nodes into and out of the cluster while doing mutations and
        deletions.
        Use 'zone' param to have nodes divided into server groups by having zone > 1.

        This test begins by loading a given number of items into the cluster. It then
        adds one node, rebalances that node into the cluster, and then rebalances it back
        out. During the rebalancing we update half of the items in the cluster and delete
        the other half. Once the node has been removed and added back we recreate the
        deleted items, wait for the disk queues to drain, and then verify that there has
        been no data loss, sum(curr_items) match the curr_items_total. We then remove and
        add back two nodes at a time and so on until we have reached the point
        where we are adding back and removing at least half of the nodes.
        """
        self.add_remove_servers_and_rebalance(self.cluster.servers[self.nodes_init:self.num_servers], [])
        gen_delete = self.get_doc_generator(self.num_items / 2 + 2000, self.num_items)
        for i in reversed(range(self.num_servers)[self.num_servers / 2:]):
            tasks =[]
            tasks.append(self.task.async_load_gen_docs_atomicity(self.cluster, self.def_bucket,
                                             self.gen_update, "rebalance_update" , exp=0,
                                             batch_size=10,
                                             process_concurrency=8,
                                             replicate_to=self.replicate_to,
                                             persist_to=self.persist_to, timeout_secs=self.sdk_timeout,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit
                                             ,durability=self.durability_level, sync=self.sync))
            
            tasks.append(self.task.async_load_gen_docs_atomicity(self.cluster, self.def_bucket,
                                             gen_delete, "rebalance_delete" , exp=0,
                                             batch_size=10,
                                             process_concurrency=8,
                                             replicate_to=self.replicate_to,
                                             persist_to=self.persist_to, timeout_secs=self.sdk_timeout,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit
                                             ,durability=self.durability_level, sync=self.sync))

            self.add_remove_servers_and_rebalance([], self.cluster.servers[i:self.num_servers])
            self.sleep(60)
            self.add_remove_servers_and_rebalance(self.cluster.servers[i:self.num_servers], [])
            for task in tasks:
                self.task_manager.get_task_result(task)
            task = self.task.async_load_gen_docs_atomicity(self.cluster, self.def_bucket,
                                             gen_delete, "create" , exp=0,
                                             batch_size=10,
                                             process_concurrency=8,
                                             replicate_to=self.replicate_to,
                                             persist_to=self.persist_to, timeout_secs=self.sdk_timeout,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit
                                             ,durability=self.durability_level, sync=self.sync)
            self.task_manager.get_task_result(task)
            self.sleep(20)
#             self.bucket_util.verify_cluster_stats(self.num_items)


    def test_rebalance_in_out_at_once(self):
        """
        PERFORMANCE:Rebalance in/out at once.
        Use different nodes_in and nodes_out params to have uneven add and deletion. Use 'zone'
        param to have nodes divided into server groups by having zone > 1.


        Then it creates cluster with self.nodes_init nodes. Further
        test loads a given number of items into the cluster. It then
        add  servs_in nodes and remove  servs_out nodes and start rebalance.
        Once cluster was rebalanced the test is finished.
        Available parameters by default are:
        nodes_init=1, nodes_in=1, nodes_out=1
        """
        gen = self.get_doc_generator(0, self.num_items)
        task = self.task.async_load_gen_docs_atomicity(self.cluster, self.def_bucket,
                                             gen, "create" , exp=0,
                                             batch_size=10,
                                             process_concurrency=8,
                                             replicate_to=self.replicate_to,
                                             persist_to=self.persist_to, timeout_secs=self.sdk_timeout,
                                             retries=self.sdk_retries, transaction_timeout=self.transaction_timeout, commit=self.transaction_commit
                                             ,durability=self.durability_level, sync=self.sync)
        try:
            self.task_manager.get_task_result(task)
        except ExecutionException:
            pass
        self.sleep(20)
        servs_init = self.cluster.servers[:self.nodes_init]
        servs_in = [self.cluster.servers[i + self.nodes_init] for i in range(self.nodes_in)]
        servs_out = [self.cluster.servers[self.nodes_init - i - 1] for i in range(self.nodes_out)]
        rest = RestConnection(self.cluster.master)
        self.bucket_util._wait_for_stats_all_buckets()
        self.log.info("current nodes : {0}".format([node.id for node in rest.node_statuses()]))
        self.log.info("adding nodes {0} to cluster".format(servs_in))
        self.log.info("removing nodes {0} from cluster".format(servs_out))
        result_nodes = set(servs_init + servs_in) - set(servs_out)
        self.add_remove_servers_and_rebalance(servs_in, servs_out)
        self.sleep(10)
#         self.bucket_util.verify_cluster_stats(self.num_items)
        self.bucket_util.verify_unacked_bytes_all_buckets()

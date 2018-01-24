# -*- mode: python; python-indent: 4 -*-
import ncs
from ncs.application import Service
from ncs.dp import Action
from ncs.maapi import Maapi
import json
import threading
import os
from loopback.utils import apply_template, plan_data_service, get_xpath


# --------------------------------------------------
# Global service configuration parameters
# --------------------------------------------------
class Config(object):
    ID_POOL = 'pool-1'


# ---------------------------------------------
# SERVICES
# ---------------------------------------------
class LoopbackService(Service):
    @Service.create
    @plan_data_service('loopback:requested-allocations')
    def cb_create(self, tctx, root, service, proplist, self_plan):

        r_vars = {
            'POOL_NAME': Config.ID_POOL,
            'ALLOCATION_ID': '{}-{}'.format(service.name, 1),
        }
        apply_template('resource-request', service, r_vars)

        self_plan.set_reached('loopback:requested-allocations')

        alloc_id = id_read(tctx.username, root, Config.ID_POOL, '{}-{}'.format(service.name, 1))
        self.log.info('ID is {}'.format(alloc_id))
        if alloc_id is None:
            apply_template('service-callback', service, r_vars)
            return

        t_vars = {
            'ADDRESS': '1.2.3.{}'.format(alloc_id),
            'MASK': '255.255.255.255',
        }
        apply_template('loopback-template', service, t_vars)

        return proplist


class SetupService(Service):
    @Service.create
    def cb_create(self, tctx, root, service, proplist):
        t_vars = {
            'POOL_NAME': Config.ID_POOL,
        }
        apply_template('setup-template', service, t_vars)


# ---------------------------------------------
# ACTIONS
# ---------------------------------------------
class DiffIterAction(Action):
    @Action.action
    def cb_action(self, uinfo, name, kp, input, output):

        def iterate(keypath, op, old_value, new_value):
            self.log.info('Diff iterate: kp: {}, op: {}'.format(keypath, DiffOps(op)))

            if op == ncs.MOP_CREATED and len(keypath) > 3 and str(keypath[0]) == 'request':
                # /loopback:resource-manager/id-pool{pool-1}/allocation{XR-0-1}/request
                allocation_id = kp_value(keypath[1])
                pool_name = kp_value(keypath[3])

                assigned_id = id_allocator.allocate(allocation_id, pool_name)

                if assigned_id is None:
                    self.log.error('Resource pool {} exhausted'.format(pool_name))
                else:
                    with ncs.maapi.single_write_trans(uinfo.username, uinfo.context, db=ncs.OPERATIONAL) as write_t:
                        ncs.maagic.get_node(write_t, keypath)._parent.response.assigned_id = assigned_id
                        write_t.apply()

                    self.log.info('Allocate: {}, {}, value: {}'.format(pool_name, allocation_id, assigned_id))

            elif op == ncs.MOP_DELETED and len(keypath) > 2 and str(keypath[1]) == 'allocation':
                # /loopback:resource-manager/id-pool{pool-1}/allocation{XR-0-1}
                allocation_id = kp_value(keypath[0])
                pool_name = kp_value(keypath[2])

                diff_size = id_allocator.deallocate(allocation_id, pool_name)

                self.log.info('De-Allocate: {}, {}, {} changes'.format(pool_name, allocation_id, diff_size))

            return ncs.ITER_RECURSE
            # TODO: Replace with this when the kickers issue is figured out
            # else:
            #    return ncs.ITER_RECURSE
            #
            # return ncs.ITER_STOP

        self.log.info('Action input: kicker-id: {}, path: {}, tid: {}'.format(input.kicker_id, input.path, input.tid))

        id_allocator = FileAllocator(Config.ID_POOL)

        with Maapi() as m, m.attach(input.tid) as t:
            t.diff_iterate(iterate, ncs.ITER_WANT_P_CONTAINER)


# ---------------------------------------------
# UTILS
# ---------------------------------------------
def kp_value(kp_element):
    """
    Get the value of a keypath element as native Python type
    :param kp_element: an element of a keypath (HKeypathRef)
    :return: The element .as_pyval() or a list of it. None if element is an XmlTag
    """
    if isinstance(kp_element, tuple):
        values = [value.as_pyval() for value in kp_element]
        if len(values) == 1:
            values = values[0]

        return values

    # This an xmltag element, i.e. not a value-type key-path element
    return None


def id_read(username, root, pool_name, allocation_id):
    """Returns the allocated ID or None

    Arguments:
    username -- the requesting service's transaction's user
    root -- a maagic root for the current transaction
    pool_name -- name of pool to request from
    allocation_id -- unique allocation id
    """

    # Look in the current transaction
    id_pool_list = root.loopback__resource_manager.id_pool
    if pool_name not in id_pool_list:
        raise LookupError("Pool {} does not exist".format(pool_name))
    if allocation_id not in id_pool_list[pool_name].allocation:
        raise LookupError("Allocation {} does not exist in pool {}".format(allocation_id, pool_name))

    # Now we switch from the current transaction to actually see if we have received the allocation
    with ncs.maapi.single_read_trans(username, "system", db=ncs.OPERATIONAL) as th:
        id_pool_list = ncs.maagic.get_root(th).loopback__resource_manager.id_pool
        if pool_name not in id_pool_list:
            return None

        id_pool = id_pool_list[pool_name]
        if allocation_id not in id_pool.allocation:
            return None

        return id_pool.allocation[allocation_id].response.assigned_id


class FileAllocator(object):
    _lock = threading.Lock()

    init_pool_data = {'range': {'start': 1, 'end': 10}, 'allocations': []}

    def __init__(self, default_pool=None, db_file=None):
        self._db_file = os.path.join('resource-pools.json') if db_file is None else db_file

        if not os.path.exists(self._db_file):
            if default_pool is not None:
                self._save({default_pool: FileAllocator.init_pool_data})
            else:
                raise FileNotFoundError('Pool database file not found: {}'.format(self._db_file))

    def allocate(self, allocation_id, pool_name):
        with FileAllocator._lock:
            pool_db = self._load()

            items_pool = range(pool_db[pool_name]['range']['start'], pool_db[pool_name]['range']['end'] + 1)
            items_taken = {allocation['value'] for allocation in pool_db[pool_name]['allocations']}
            items_avail = filter(lambda item: item not in items_taken, items_pool)

            assigned = next(iter(items_avail), None)
            if assigned is not None:
                pool_db[pool_name]['allocations'].append({'id': allocation_id, 'value': assigned})
                self._save(pool_db)

            return assigned

    def deallocate(self, allocation_id, pool_name):
        with FileAllocator._lock:
            pool_db = self._load()

            old_alloc_size = len(pool_db[pool_name]['allocations'])
            new_alloc = [item for item in pool_db[pool_name]['allocations'] if item['id'] != allocation_id]

            num_removals = old_alloc_size - len(new_alloc)
            if num_removals > 0:
                pool_db[pool_name]['allocations'] = new_alloc
                self._save(pool_db)

            return num_removals

    def _load(self):
        with open(self._db_file) as f:
            return json.load(f)

    def _save(self, pool_db):
        with open(self._db_file, 'w') as f:
            json.dump(pool_db, f, indent=2)


class DiffOps(object):
    op_dict = {
        ncs.MOP_ATTR_SET: 'MOP_ATTR_SET',
        ncs.MOP_CREATED: 'MOP_CREATED',
        ncs.MOP_DELETED: 'MOP_DELETED',
        ncs.MOP_MODIFIED: 'MOP_MODIFIED',
        ncs.MOP_MOVED_AFTER: 'MOP_MOVED_AFTER',
        ncs.MOP_VALUE_SET: 'MOP_VALUE_SET',
    }

    def __init__(self, op):
        self.op = op

    def __str__(self):
        return '{}({})'.format(DiffOps.op_dict.get(self.op, 'unknown'), self.op)


# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY NCS.
# ---------------------------------------------
class Main(ncs.application.Application):
    def setup(self):
        # The application class sets up logging for us. It is accessible
        # through 'self.log' and is a ncs.log.Log instance.
        self.log.info('Main RUNNING')

        # Registration of service callbacks
        self.register_service('loopback-servicepoint', LoopbackService)
        self.register_service('loopback-setup', SetupService)

        # Registration of action callbacks
        self.register_action('diff-iter-action', DiffIterAction)

    def teardown(self):
        self.log.info('Main FINISHED')

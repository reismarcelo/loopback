import ncs.template
from ncs.application import PlanComponent
import functools
import re
_tm = __import__(ncs.tm.TM)


# ---------------------------------------------
# UTILITY FUNCTIONS
# ---------------------------------------------
def plan_data_service(*custom_states):
    """
    Decorator for cb_create callback. Initialize a self plan component.
    :param custom_states: additional states for the plan component
    :return: cb_create wrapper
    """
    def decorator(cb_create_method):
        @functools.wraps(cb_create_method)
        def wrapper(self, tctx, root, service, proplist):
            self.log.info('Service create ({})'.format(service._path))
            self_plan = init_plan(PlanComponent(service, 'self', 'ncs:self'), *custom_states)

            try:
                proplist = cb_create_method(self, tctx, root, service, proplist, self_plan)
                if proplist is None:
                    return
            except NcsServiceError as e:
                self.log.error(e)
                self_plan.set_failed('ncs:ready')
                raise
            else:
                self_plan.set_reached('ncs:ready')

            return proplist

        return wrapper

    return decorator


def init_plan(plan_component, *custom_states):
    """
    Initialize the states of an NCS PlanComponent object
    :param plan_component: An NCS PlanComponent object
    :param custom_states: One or more strings representing additional states supported by the plan component
    :return: The PlanComponent object
    """
    for plan_state in ['ncs:init'] + list(custom_states) + ['ncs:ready']:
        plan_component.append_state(plan_state)

    plan_component.set_reached('ncs:init')

    return plan_component


def apply_template(template_name, context, var_dict=None):
    """
    Facilitate applying templates by setting template variables via an optional dictionary

    :param template_name: Name of the template file
    :param context: Context in which the template is rendered
    :param var_dict: Optional dictionary containing additional variables to be passed to the template
    """
    template = ncs.template.Template(context)
    t_vars = ncs.template.Variables()

    if var_dict is not None:
        for name, value in var_dict.items():
            t_vars.add(name, value)

    template.apply(template_name, t_vars)


def split_intf_name(intf_name):
    """
    Split a full interface name (e.g. GigabitEthernet0/1/2/3) into interface type (e.g. GigabitEthernet)
    and id (e.g. 0/1/2/3)
    :param intf_name: string containing the full interface name
    :return: 2-tuple (<interface type>, <interface id>) or None if the name couldn't be parsed
    """
    m = re.match(r'(?P<type>[a-zA-Z-]+)(?P<id>[0-9]+[^\s]*)', intf_name)
    if m is not None:
        return m.group('type'), m.group('id')

    return None


def is_intf_sub(intf_name):
    """
    Return True if the provided interface name refers to a subinterface
    :param intf_name: interface name
    :return: True or False
    """
    return '.' in intf_name


def get_key_yang(node):
    """
    Return the yang names corresponding to the node's key(s)

    :param node: a Maagic List
    :return: list of key yang names or None if node doesn't have any key element
    """

    # keys() returns None if node doesn't have any key (e.g. not a List)
    key_hashes = node._cs_node.info().keys()

    return key_hashes and [_tm.hash2str(key_hash) for key_hash in key_hashes]


def get_xpath(service_node):
    """
    Get an xpath that resolves to the provided service node element

    Example:
        service_node: /ncs:services/ciscoas:l3-default{CUSTOMER1-L3-DEFAULT-1 Vancouver}
        return: /ncs:services/ciscoas:l3-default[service-id='CUSTOMER1-L3-DEFAULT-1'][dc-name='Vancouver']

    Please note that this function only supports service_node with a single list in its keypath. Keypaths with
    concatenated lists are not supported and will produce unexpected results.

    :param service_node: a service node object
    :return: xpath string
    """

    def replace_match(match):
        key_values = match.group(1).split()
        return ''.join(map(lambda name_value: "[{}='{}']".format(name_value[0], name_value[1]),
                           zip(service_key_names, key_values)))

    service_key_names = get_key_yang(service_node)

    return re.sub(r'{([^}]+)}', replace_match, service_node._path)


# ---------------------------------------------
# Exceptions
# ---------------------------------------------
class NcsServiceError(Exception):
    """ Exception indicating error during service create """
    pass

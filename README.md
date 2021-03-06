# Loopback package

Provided a device name this package will allocate an configure an address on its loopback interface. The goal is to
demonstrate the use of kickers to implement an external resource manager. Resource allocations are tracked in a JSON
file.

There is also code to demonstrate using custom validators in python. This is used to validate the description field.

## Initial setup

The resource allocations file 'resource-pools.json' is automatically created with some predefined defaults if it doesn't
yet exist. The default pool created is 'pool-1'.

The setup container is used primarily to configure the kickers (i.e. applying setup-template.xml). It needs to be configured
before devices can be specified.

    admin@ncs(config)# services loopback ?
    Possible completions:
      setup  <cr>
    admin@ncs(config)# services loopback setup
    admin@ncs(config-loopback)# commit
    Commit complete.

In order to view the configured kickers we need to create and unhide the debug group:

a. Add the following to ncs.conf file and restart NSO:

    <hide-group>
        <name>debug</name>
    </hide-group>

b. Unhide the debug group via cli:

    admin@ncs# unhide debug

c. Show running kickers:

    admin@ncs# show running-config kickers
    kickers data-kicker resource-diff-iter
     monitor      /loopback:external-resource-manager/loopback:id-pool/loopback:allocation
     trigger-expr request
     kick-node    /external-resource-manager
     action-name  diff-iter
    !
    <snip>


## Specifying device to configure the loopback

    admin@ncs(config)# services loopback device IOS-0
    admin@ncs(config-device-IOS-0)# commit

















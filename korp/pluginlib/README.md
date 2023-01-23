
# `korp.pluginlib`: Korp backend plugin framework (API) (proposal)


<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
## Table of contents

- [Overview](#overview)
- [Configuration](#configuration)
  - [Configuring Korp for plugins](#configuring-korp-for-plugins)
  - [Configuring `korp.pluginlib`](#configuring-korppluginlib)
  - [Configuring individual plugins](#configuring-individual-plugins)
  - [Renaming plugin endpoint routes](#renaming-plugin-endpoint-routes)
- [Plugin information](#plugin-information)
- [Endpoint plugins](#endpoint-plugins)
  - [Implementing a new WSGI endpoint](#implementing-a-new-wsgi-endpoint)
  - [Non-JSON endpoints](#non-json-endpoints)
  - [Defining additional endpoint decorators](#defining-additional-endpoint-decorators)
- [Callback plugins](#callback-plugins)
  - [Filter hook points](#filter-hook-points)
  - [Event hook points](#event-hook-points)
  - [Callback plugin example](#callback-plugin-example)
  - [Notes on implementing a callback plugin](#notes-on-implementing-a-callback-plugin)
  - [Keeping request-specific state](#keeping-request-specific-state)
  - [Defining hook points in plugins](#defining-hook-points-in-plugins)
- [Accessing main application module globals in plugins](#accessing-main-application-module-globals-in-plugins)
- [Limitations and deficiencies](#limitations-and-deficiencies)
- [Influences and alternatives](#influences-and-alternatives)
  - [Influcences](#influcences)
  - [Other Python plugin frameworks and libraries](#other-python-plugin-frameworks-and-libraries)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->


## Overview

The Korp backend supports two kinds of plugins:

1. *endpoint plugins* implementing new WSGI endpoints, and
2. *callback plugins* containing callbacks called at certain points
   (*plugin hook points*) in `korp.py` when handling a request, to
   filter data or to perform an action.

Plugins are defined as Python modules or subpackages, by default
within the package `korpplugins` (customizable via the configuration
variable `PACKAGES`; see [below](#configuring-korppluginlib)).

Both WSGI endpoint plugins and callback plugins can be defined in the
same plugin module.


## Configuration


### Configuring Korp for plugins

Korp’s `config.py` (that is, top-level module `config`) contains the
following plugin-related variables:

- `PLUGINS`: A list of names of plugins (modules or subpackages) to be
  used, in the order they are to be loaded. If a plugin module is not
  found, a warning is output to the standard output.

- `INFO_SHOW_PLUGINS`: What information on loaded plugins the response
  of the `/info` command should contain:
  - `None` or `""`: nothing
  - `"names"`: `plugins` as a list of names of plugins as specified in
    `PLUGINS`
  - `"info"`: `plugins` as a list of objects with `name` as the name
    of the plugin as specified in `PLUGINS` and `info` as the
    information specified in the `PLUGIN_INFO` dictionary defined in
    the plugin module (see [below](#plugin-information)


### Configuring `korp.pluginlib`

The configuration of `korp.pluginlib` is in the module
`korp.pluginlib.config` (file `korp.pluginlib/config.py`). Currently,
the following configuration variables are recognized:

- `PACKAGES`: A list of packages which may contain plugins; default:
  `["korpplugins"]`. The packages may be namespace packages, so their
  modules may be under different directory roots. An empty string
  denotes top-level modules without packages. The packages are
  searched for a plugin in the order in which they are listed.

- `SEARCH_PATH`: A list of directories in which to search for plugins
  (the packages listed in `PACKAGES`) in addition to default ones
  (appended to `sys.path`); default: `[]`.

- `HANDLE_NOT_FOUND`: What to do when a plugin is not found:
    - `"error"`: Throw an error.
    - `"warn"` (default): Output a warning to the standard error but
      continue.
    - `"ignore"`: Silently ignore.

- `LOAD_VERBOSITY`: What `korp.pluginlib` outputs when loading plugins:
    - `0`: nothing
    - `1` (default): the names of loaded plugins only
    - `2`: the names of loaded plugins and their possible
      configurations, and the view functions handling a route or
      callback methods registered for a hook point

- `HANDLE_DUPLICATE_ROUTES`: What to do with duplicate endpoints for a
  routing rule, added by plugins:
    - `"override"`: Use the endpoint defined last without printing
      anything, allowing a plugin to override an endpoint defined in
      `korp.py`; if multiple plugins define an endpoint for the same
      route, the last one is used.
    - `"override,warn"` (default): Use the endpoint defined last and
      print a warning to stderr.
    - `"ignore"`: Use the endpoint defined first (Flask default
      behaviour) without printing anything.
    - `"warn"`: Use the endpoint defined first (Flask default) and
      print a warning message to stderr.
    - `"error"`: Print an error message to stderr and raise a
      `ValueError`.

Alternatively, the configuration variables may be specified in the
top-level module `config` within the dictionary or namespace object
`PLUGINLIB_CONFIG`; for example:

```python
PLUGINLIB_CONFIG = dict(
    HANDLE_NOT_FOUND = "warn",
    LOAD_VERBOSITY = 1,
)
```

The values specified in the top-level `config` override those in
`korp.pluginlib.config`.


### Configuring individual plugins

Values for the configuration variables of individual plugin modules or
subpackages can be specified in three places:

1. An item in the list `PLUGINS` in Korp’s top-level `config` module
   can be a pair `(`_plugin\_name_`,` _config_`)`, where _config_ may
   be either a dictionary- or namespace-like object containing
   configuration variables.

2. Korp’s top-level `config` module can define the variable
   `PLUGIN_CONFIG_`_PLUGINNAME_ (where _PLUGINNAME_ is the name of the
   plugin in upper case), whose value may be either a dictionary- or
   namespace-like object with configration variables.

3. If the plugin is a subpackage (and not a single module), it can use
   separate configuration module named `config` within the package,
   consisting of configuration variables.

The value for a configuration variable is taken from the first of the
above in which it is set.

To get values from these sources, the plugin module needs to call
`korp.pluginlib.get_plugin_config` with default values of configuration
variables. The function returns an object containing configuration
variables with their values (an instance of `types.SimpleNamespace`).
For example:

```python
pluginconf = korp.pluginlib.get_plugin_config(
    CONFIG_VAR = "value",
)
```
The configured value of `CONFIG_VAR` can be then accessed as
`pluginconf.CONFIG_VAR`. Once the plugin has been loaded, other
plugins can also access it as
`korp.pluginlib.plugin_configs["`_plugin_`"].CONFIG_VAR`.

Note that the value returned by `get_plugin_config` contains values
only for the keys specified in the default values given as arguments,
even if the other places for configuration variables defined
additional variables. (If `get_plugin_config` is called without
arguments, the values defined in a possible configuration module are
taken as defaults.) The default values can be specified either as
keyword arguments to `get_plugin_config` or as a single value that can
be either a dictionary- or namespace-like object. The returned value
is always a `SimpleNamespace`.


### Renaming plugin endpoint routes

Endpoint routes (routing rules) defined by a plugin can be renamed by
setting an appropriate value to the configuration variable
`RENAME_ROUTES` of the plugin in question. This may be needed if two
plugins have endpoints with the same route, or if it is otherwise
desired to change the routes specified by a plugin.

The default value of `RENAME_ROUTES` is `None`, meaning that routes
are not renamed. Otherwise, its value can be a string, `dict` or
function (`(str) -> str`):

- A string value is used to rename all the routes defined by a plugin.
  It is a format string in which `{}` denotes the original route
  (without the leading a slash): for example, the value `"x_{}"` would
  rename `/test1` to `/x_test1` and `/test2` to `/x_test2`.
- A `dict` value is used to rename individual routes: for example,
  `{"test1": "xtest"}` would rename `/test1` to `/xtest` but keep all
  other routes intact.
- A function value can be used to rename all routes more flexibly than
  a format string. The function takes the route as an argument string
  and returns the renamed route. For example, `lambda r: r[-1] +
  r[:-1]` would rename `/test1` to `/1test` and `/test2` to `/2test`.

Note that in all cases, the leading slash is stripped from the route
before renaming and prepended again after it.

Note that the configuration variable `RENAME_ROUTES` can always be set
in a plugin configuration even if it had not been given a default
value in the plugin. `RENAME_ROUTES` is also present in the
configuration of plugins with no endpoints even if it has no effect
there.


## Plugin information

A plugin module or package may define `dict` `PLUGIN_INFO` containing
pieces of information on the plugin. Alternatively, a plugin package
may contain module named `info` and a non-package plugin module
_plugin_ may be accompanied with a module named _plugin_`_info`
containing variable definitions that are added to `PLUGIN_INFO` with
the lower-cased variable name as the key. (As their values are
constant, it is suggested that the variable names in the `info` module
are written in upper case.) If both `PLUGIN_INFO` and an `info` module
contain a value for the same key, the value in `PLUGIN_INFO` takes
precedence.

Plugin information should contain values for at least the keys
`"name"`, `"version"` and `"date"`, and preferably also
`"description"` and possibly `"author"`. Others may be freely added as
needed. The first three are shown in the plugin load message if
defined (and if `LOAD_VERBOSITY` is at least 1). For example:

```python
PLUGIN_INFO = {
    "name": "korp.pluginlib_test_1",
    "version": "0.1",
    "date": "2020-12-10",
    "description": "korp.pluginlib test plugin 1",
    "author": "FIN-CLARIN",
    "author_email": "fin-clarin at helsinki dot fi",
}
```

Or equivalently in an `info` module:

```python
NAME = "korp.pluginlib_test_1"
VERSION = "0.1"
DATE = "2020-12-10"
DESCRIPTION = "korp.pluginlib test plugin 1"
AUTHOR = "FIN-CLARIN"
AUTHOR_EMAIL = "fin-clarin at helsinki dot fi"
```

The information on loaded plugins is accessible in the variable
`korp.pluginlib.loaded_plugins`. Its value is an `OrderedDict` whose
keys are plugin names and values are `dict`s with the value of the key
`"module"` containing the plugin module object and the rest taken from
the `PLUGIN_INFO` defined in the plugin. The values in
`loaded_plugins` are in the order in which the plugins have been
loaded.


## Endpoint plugins


### Implementing a new WSGI endpoint

To implement a new WSGI endpoint, you first create an instance of
`korp.pluginlib.EndpointPlugin` (a subclass of `flask.Blueprint`)
as follows:

```python
test_plugin = korp.pluginlib.EndpointPlugin()
```

You can also specify a name for the plugin, overriding the default
that is the calling module name `__name__`:

```python
test_plugin = korp.pluginlib.EndpointPlugin("test_plugin")
```

You may also pass other arguments recognized by `flask.Blueprint`.

The actual view function is a generator function decorated with the
`route` method of the created instance; for example:

```python
@test_plugin.route("/test", extra_decorators=["prevent_timeout"])
def test(args):
    """Yield arguments wrapped in "args"."""
    yield {"args": args}
```

The decorator takes as its arguments the route of the endpoint, and
optionally, an iterable of the names of possible additional decorators
as the keyword argument `extra_decorators` and other options of
`route`. `extra_decorators` lists the names in the order in which they
would be specified as decorators (topmost first), that is, in the
reverse order of application. The generator function takes a single
`dict` argument containing the parameters of the call and yields the
result.

A single plugin module can define multiple new endpoints.

The routes for endpoints defined by a plugin can be renamed by setting
the plugin configuration variable `RENAME_ROUTES` appropriately; see
[above](#renaming-plugin-endpoint-routes).


### Non-JSON endpoints

Even though Korp endpoints should in general return JSON data, it may
be desirable to implement endpoints returning another type of data,
for example, if the endpoint generates a file for downloading. That
can be accomplished by adding `use_custom_headers` to
`extra_decorators`. An endpoint using `use_custom_headers` should
yield a `dict` with the following keys recognized:

- `"content"`: the actual content;
- `"mimetype"` (default: `"text/html"`): possible MIME type; and
- `"headers"`: possible other headers as a list of pairs (_header_,
  _value_).

For example, the following endpoint returns an attachment for a
plain-text file listing the arguments to the endpoint, named with the
value of `filename` (`args.txt` if not specified):

```python
@test_plugin.route("/text", extra_decorators=["use_custom_headers"])
def textfile(args):
    """Make downloadable plain-text file of args."""
    yield {
        "content": "\n".join(arg + "=" + repr(args[arg]) for arg in args),
        "mimetype": "text/plain",
        "headers": [
            ("Content-Disposition",
             "attachment; filename=\"" + args.get("filename", "args.txt")
             + "\"")]
    }
```

Note that neither the endpoint argument `incremental=true` nor the
decorator `prevent_timeout` has any practical effect on endpoints with
`use_custom_headers`.


### Defining additional endpoint decorators

By default, the endpoint decorator functions whose names can be listed
in `extra_decorators` include only `prevent_timeout` and
`use_custom_headers`, as the endpoints defined in this way are always
decorated with `main_handler` as the topmost decorator. However,
additional decorator functions can be defined by decorating them with
`korp.pluginlib.EndpointPlugin.endpoint_decorator`; for example:

```python
# test_plugin is an instance of korp.pluginlib.EndpointPlugin, so this
# is equivalent to @korp.pluginlib.EndpointPlugin.endpoint_decorator
@test_plugin.endpoint_decorator
def test_decor(generator):
    """Add to the result an extra layer with text_decor and payload."""
    @functools.wraps(generator)
    def decorated(args=None, *pargs, **kwargs):
        for x in generator(args, *pargs, **kwargs):
            yield {"test_decor": "Endpoint decorated with test_decor",
                   "payload": x}
    return decorated
```


## Callback plugins

Callbacks to be called at specific *plugin hook points* in `korp.py`
are defined within subclasses of `korp.pluginlib.CallbackPlugin` as
instance methods having the name of the hook point. The arguments and
return values of a callback method are specific to a hook point.

In the first argument `request`, each callback method gets the actual Flask
request object (not a proxy for the request) containing information on
the request. For example, the endpoint name is available as
`request.endpoint`.

`korp.py` contains two kinds of hook points:

1. *filter hook points* call callbacks that may filter (modify) a
   value, and
2. *event hook points* call callbacks when a specific event has taken
   place.


### Filter hook points

For filter hook points, the value returned by a callback method is
passed as the first non-`request` argument to the callback method
defined by the next plugin, similar to function composition or method
chaining. However, a callback for a filter hook point *need not*
modify the value: if the returned value is `None`, either explicitly
or if the method has no `return` statement with a value, the value is
ignored and the argument is passed as is to the callback method in the
next plugin. Thus, a callback method that does not modify the value
need not return it.

Filter hook points and the signatures of their callback methods are
the following:

- `filter_args(self, request, args)`: Modifies the arguments
  `dict` `args` to any endpoint (view function) and returns the
  modified value.

- `filter_result(self, request, result)`: Modifies the result `dict`
  `result` returned by any endpoint (view function) and returns the
  modified value.

  *Note* that when the arguments (query parameters) of the endpoint
  contain `incremental=true`, `filter_result` is called separately for
  each incremental part of the result, typically `progress_corpora`,
  `progress_`_num_ (where _num_ is the number of corpus), the actual
  content body, and possibly `hits`, `corpus_hits`, `corpus_order` and
  `query_data` as a single part. (Currently, `filter_result` is *not*
  called for `time`.) Thus, you should not assume that the value of
  the `result` argument always contains the content body.

- `filter_cqp_input(self, request, cqp)`: Modifies the raw CQP
  input string `cqp`, typically consisting of multiple CQP commands,
  already encoded as `bytes`, to be passed to the CQP executable, and
  returns the modified value.

- `filter_cqp_output(self, request, (output, error))`: Modifies
  the raw output of the CQP executable, a pair consisting of the
  standard output and standard error encoded as `bytes`, and returns
  the modified values as a pair.

- `filter_sql(self, request, sql)`: Modifies the SQL statement
  `sql` to be passed to the MySQL/MariaDB database server and returns
  the modified value.

- `filter_protected_corpora(self, request, protected_corpora)`:
  Modifies (or replaces) the list `protected_corpora` of ids of
  protected corpora, the use of which requires authentication and
  authorization.

- `filter_auth_postdata(self, request, postdata)`: Modifies (or
  replaces) the POST request parameters in `postdata`, to be passed to
  the authorization server (`config.AUTH_SERVER`) in the endpoint
  `/authenticate`.

- `filter_auth_response(self, request, auth_response)`: Modifies the
  response `auth_response` returned by the authorization server in the
  endpoint `/authenticate`.


### Event hook points

Callback methods for event hook points do not return a value. (A
possible return value is ignored.)

Event hook points and the signatures of their callback methods are the
following:

- `enter_handler(self, request, args, starttime)`: Called near
  the beginning of a view function for an endpoint. `args` is a `dict`
  of arguments to the endpoint and `starttime` is the current time as
  seconds since the epoch as a floating point number.

- `exit_handler(self, request, endtime, elapsed_time, result_len)`:
  Called just before exiting a view function for an endpoint (before
  yielding a response). `endtime` is the current time as seconds since
  the epoch as a floating point number, `elapsed_time` is the time
  spent in the view function as seconds, and `result_len` the length
  of the response content.

- `error(self, request, error, exc)`: Called after an exception
  has occurred. `error` is the `dict` to be returned in JSON as
  `ERROR`, with keys `type` and `value` (and `traceback` if
  `debug=true` had been specified), and `exc` contains exception
  information as returned by `sys.exc_info()`.


### Callback plugin example

An example of a callback plugin containing a callback method to be
called at the hook point `filter_result`:

```python
class Test1b(korp.pluginlib.CallbackPlugin):

    def filter_result(self, request, result):
        """Wrap the result dictionary in "wrap" and add "endpoint"."""
        return {"endpoint": request.endpoint,
                "wrap": result}
```


### Notes on implementing a callback plugin

Each plugin class is instantiated only once (it is a singleton), so
the possible state stored in `self` is shared by all invocations
(requests). However, see [the next
subsection](#keeping-request-specific-state) for an approach of
keeping request-specific state across hook points.

A single plugin class can define only one callback method for each
hook point, but a module may contain multiple classes defining
callback methods for the same hook point.

If multiple plugins define a callback method for a hook point, they
are called in the order in which the plugin modules are listed in
`config.PLUGINS`. If a plugin module contains multiple classes
defining a callback method for a hook point, they are called in the
order in which they are defined in the module.

If the callback methods of a class should be applied only to certain
kinds of requests, for example, to a certain endpoint, the class can
override the class method `applies_to(cls, request)` to return `True`
only for requests to which the plugin is applicable. (The parameter
`request` is the actual Flask request object, not a proxy.)


### Keeping request-specific state

Request-specific data can be passed from one callback method to
another within the same callback plugin class by using a `dict`
attribute (or similar) indexed by request objects (or their ids). In
general, the `enter_handler` callback method (called at the first hook
point) should initialize a space for the data for a request, and
`exit_handler` (called at the last hook point) should delete it. For
example:

```python
from types import SimpleNamespace

class StateTest(korp.pluginlib.CallbackPlugin):

    _data = {}

    def enter_handler(self, request, args, starttime):
        self._data[request] = data = SimpleNamespace()
        data.starttime = starttime
        print("enter_handler, starttime =", starttime)

    def exit_handler(self, request, endtime, elapsed):
        print("exit_handler, starttime =", self._data[request].starttime,
              "endtime =", endtime)
        del self._data[request]
```

This works in part because the `request` argument of the callback
methods is the actual Flask request object, not the global proxy.


### Defining hook points in plugins

In addition to the hook points in `korp.py` listed above, you can
define hook points in plugins by invoking callbacks with the name of
the hook point by using the appropriate methods. For example, a
logging plugin could implement a callback method `log` that could be
called from other plugins, both callback and endpoint plugins.

Given the Flask request object (or the global request proxy)
`request`, callbacks for the (event) hook point `hook_point` can be
called as follows, with `*args` and `**kwargs` as the positional and
keyword arguments and discarding the return value:

```python
korp.pluginlib.CallbackPluginCaller.raise_event_for_request(
    "hook_point", *args, **kwargs, request=request)
```

or, equivalently, getting a caller object for a request and calling
its instance method (typically when the same function or method
contains several hook points):

```python
plugin_caller = korp.pluginlib.CallbackPluginCaller.get_instance(request)
plugin_caller.raise_event("hook_point", *args, **kwargs)
```

If `request` is omitted or `None`, the request object referred to by
the global request proxy is used.

Callbacks for such additional hook points are defined in the same way
as for those in `korp.py`. The signature corresponding to the above
calls is

```python
hook_point(self, request, *args, **kwargs)
```

All callback methods need to have `request` as the first positional
argument (after `self`).

Three types of call methods are available in CallbackPluginCaller:

- `raise_event_for_request` (and instance method `raise_event`): Call
  the callback methods and discard their possible return values (for
  event hook points).

- `filter_value_for_request` (and `filter_value`): Call the callback
  methods and pass the return value as the first argument of the next
  callback method, and return the value returned by the last callback
  emthod (for filter hook points).

- `get_values_for_request` (and `get_values`): Call the callback
  methods, collect their return values to a list and finally return
  the list.

Only the first two are currently used in `korp.py`.


## Accessing main application module globals in plugins

The values of selected global variables, constants and functions in
the main application module `korp.py` are available to plugin modules
in the attributes of `korp.pluginlib.app_globals`, thus accessible as
`korp.pluginlib.app_globals.`_name_. The variables and constants
currently available are `app`, `mysql`, `mc_pool`, `KORP_VERSION`,
`END_OF_LINE`, `LEFT_DELIM`, `RIGHT_DELIM`, `IS_NUMBER`, `IS_IDENT`
and `QUERY_DELIM`. In addition, several helper functions defined in
`korp.py` and useful in at least endpoint plugins can be accessed
similarly. In this way, for example, a plugin can access the Korp
MySQL database and the Memcached cache and use `assert_key` to assert
the format of arguments.


## Limitations and deficiencies

The current implementation has at least the following limitations and
deficiencies, which might be subjects for future development, if
needed:

- In endpoint plugins, it is not possible to modify the functionality
  of an existing endpoint, for example, by calling an existing view
  function from a function defined in a plugin, possibly modifying the
  arguments or the result. However, in many cases, a similar effect
  can be achieved by defining the appropriate callback methods for
  hook points `filter_args` and `filter_result`; see
  [above](#filter-hook-points).

- The order of calling the callbacks for a hook point is determined by
  the order of plugins listed in `config.PLUGINS`. The plugins
  themselves cannot specify that they should be loaded before or after
  another plugin. Moreover, in some cases, it might make sense to call
  one callback of a plugin before those of other plugins (such as
  `filter_args`) and another after those of others (such as
  `filter_result`), in a way wrapping the others (from previously
  loaded plugins). What would be a sufficiently flexible way to allow
  more control of callback order? In
  [Flask-Plugins](https://flask-plugins.readthedocs.io/en/master/),
  one can specify that a callback (event listener) is called before
  the previously registered ones instead of after them (the default).

- It might be possible for a single callback plugin class to implement
  multiple callbacks for the same hook point if a decorator was used
  to register callback methods for a hook point, instead of or as an
  alternative to linking methods to a hook point by their name. But
  would that be useful?

- A plugin cannot require that another plugin should have been loaded
  nor can it request other plugins to be loaded, at least not easily.
  However, it might not be difficult to add a facility in which
  `korp.pluginlib.load` would check if a plugin module just imported
  had specified that it requires certain other plugins and call itself
  recursively to load them. They would be loaded only after the
  requiring plugin, however. If the requirements were specified in the
  `info` module of a plugin that the plugin loader could inspect
  before loading plugins, it might be possible to order loading the
  plugins more properly.

- Plugins cannot be chosen based on their properties, such as their
  version (for example, load the most recent version of a plugin
  available on the search path) or what endpoints or callbacks they
  provide.

  One option for implementing such functionality would be to have such
  information in the plugin `info` module that the plugin loader would
  inspect before actually importing the plugin module, as in
  [Flask-Plugins](https://flask-plugins.readthedocs.io/en/master/)
  (which however uses JSON files).

- The version and date information in `PLUGIN_INFO` or an `info`
  module requires manual updating whenever the plugin is changed. An
  alternative or complementary way of adding such information would be
  to get the information from the latest Git commit of the plugin,
  typically the abbreviated commit hash and author or commit date.
  (This of course supposes that the plugin resides in a Git
  repository.) Apparently, the recommended way of including the
  information is to have an installation script that generates a file
  that contains the information and that is excluded from the
  repository. If the plugin loader knows of and finds such a file
  containing Git commit information in a format it recognizes, it
  could add the information to `PLUGIN_INFO` and the information could
  also be output when loading the plugins.

- Accessing helper functions in `korp.py` via
  `korp.pluginlib.app_globals` is somewhat cumbersome. It could be
  simplified by moving the helper functions to a separate library
  module that could be imported by plugins.

- Unlike callback methods, endpoint view functions are not methods in
  a class, as at least currently, `main_handler` and `prevent_timeout`
  cannot decorate an instance method. Possible ideas for solving that:
  https://stackoverflow.com/a/1288936,
  https://stackoverflow.com/a/36067926

- Plugins are not loaded on demand. However, loading on demand would
  probably make sense only for endpoint plugins, which could be loaded
  when an endpoint is accessed. Even then, the advantage of on-demand
  loading might not be large.


## Influences and alternatives

Many Python plugin frameworks or libraries exist, but they did not
appear suitable for Korp plugins as such. In particular, we wished to
have both callback plugins and endpoint plugins.


### Influcences

Using a metaclass for registering callback plugins in `korp.pluginlib`
was inspired by and partially adapted from Marty Alchin’s [A Simple
Plugin
Framework](http://martyalchin.com/2008/jan/10/simple-plugin-framework/).

The terms used in conjunction with callback plugins were partially
influenced by the terminology for [WordPress
plugins](https://developer.wordpress.org/plugins/hooks/).

The [Flask-Plugins](https://flask-plugins.readthedocs.io/en/master/)
Flask extension might have been a natural choice, as Korp is a Flask
application, but it was not immediately obvious if it could have been
used to implement new endpoints. Moreover, for callback (event)
plugins, it would have had to be extended to support passing the
result from one plugin callback as the input of another.

Using Flask Blueprints for endpoint plugins was hinted at by Martin
Hammarstedt.


### Other Python plugin frameworks and libraries

- [PluginBase](https://github.com/mitsuhiko/pluginbase)

- [stevedore](https://docs.openstack.org/stevedore/latest/) (uses
  [Setuptools](https://github.com/pypa/setuptools))

- [Pluginlib](https://pluginlib.readthedocs.io/en/stable/)

- [Ideas for a minimal Python plugin architecture on
  StackOverflow](https://stackoverflow.com/questions/932069/building-a-minimal-plugin-architecture-in-python)

- [A list of Python plugin frameworks from
  2009](http://wehart.blogspot.com/2009/01/python-plugin-frameworks.html)

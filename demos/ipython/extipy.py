"""
Kernel manager for connecting to a IPython kernel started outside of Jupyter.
Use this kernel manager if you want to connect a Jupyter notebook to a IPython
kernel started outside of Jupyter.
"""
import os
import os.path

from notebook.services.kernels.kernelmanager import MappingKernelManager
from tornado import gen
from tornado.concurrent import Future
from tornado.ioloop import IOLoop


class ExternalIPythonKernelManager(MappingKernelManager):
    """A Kernel manager that connects to a IPython kernel started outside of Jupyter"""

    def _attach_to_pyxll_kernel(self, kernel_id):
        """Attach to the externally started IPython kernel
        """
        self.log.info(f'Attaching {kernel_id} to an existing kernel...')
        kernel = self._kernels[kernel_id]
        port_names = ['shell_port', 'stdin_port', 'iopub_port', 'hb_port', 'control_port']
        port_names = kernel._random_port_names if hasattr(kernel, '_random_port_names') else port_names
        for port_name in port_names:
            setattr(kernel, port_name, 0)

        # Connect to kernel started by PyXLL
        connection_dir = os.path.join(os.environ["APPDATA"], "jupyter", "runtime")
        connection_fname = os.environ["PYXLL_IPYTHON_CONNECTION_FILE"]
        self.log.info(f'PyXLL IPython kernel = {connection_dir}/{connection_fname}')
        kernel.load_connection_file(os.path.join(connection_dir, connection_fname))

    @gen.coroutine
    def start_kernel(self, **kwargs):
        """Maybe switch to the kernel started by PyXLL.
        """
        kernel_id = super(ExternalIPythonKernelManager, self).start_kernel(**kwargs).result()
        self._attach_to_pyxll_kernel(kernel_id)
        raise gen.Return(kernel_id)

    def restart_kernel(self, kernel_id):
        """Maybe switch to the most recently started kernel
        Restart the kernel like normal. If `self.runtime_dir/.pynt` exists then
        attach to the most recently started kernel.
        TODO Most of this code is copied straight from
        `MappingKernelManager.restart_kernel()`. Figure out what subset of it
        is needed for this to work.
        """
        self._check_kernel_id(kernel_id)
        super(MappingKernelManager, self).restart_kernel(kernel_id)
        kernel = self.get_kernel(kernel_id)
        # return a Future that will resolve when the kernel has successfully restarted
        channel = kernel.connect_shell()
        future = Future()

        def finish():
            """Common cleanup when restart finishes/fails for any reason."""
            if not channel.closed():
                channel.close()
            loop.remove_timeout(timeout)
            kernel.remove_restart_callback(on_restart_failed, 'dead')
            self._attach_to_pyxll_kernel()

        def on_reply(msg):
            self.log.debug("Kernel info reply received: %s", kernel_id)
            finish()
            if not future.done():
                future.set_result(msg)

        def on_timeout():
            self.log.warning("Timeout waiting for kernel_info_reply: %s", kernel_id)
            finish()
            if not future.done():
                future.set_exception(gen.TimeoutError("Timeout waiting for restart"))

        def on_restart_failed():
            self.log.warning("Restarting kernel failed: %s", kernel_id)
            finish()
            if not future.done():
                future.set_exception(RuntimeError("Restart failed"))

        kernel.add_restart_callback(on_restart_failed, 'dead')
        kernel.session.send(channel, "kernel_info_request")
        channel.on_recv(on_reply)
        loop = IOLoop.current()
        timeout = loop.add_timeout(loop.time() + 30, on_timeout)
        return future

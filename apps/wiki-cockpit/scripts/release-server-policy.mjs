import net from "node:net";

export async function assertReleasePortAvailable(port, host = "127.0.0.1") {
  if (!Number.isInteger(port) || port < 1024 || port > 65535) {
    throw new Error("release preview port is invalid");
  }
  const probe = net.createServer();
  try {
    await new Promise((resolve, reject) => {
      probe.once("error", reject);
      probe.listen(port, host, resolve);
    });
  } catch (error) {
    throw new Error("release preview port is already occupied; stale server refused", {
      cause: error
    });
  } finally {
    if (probe.listening) {
      await new Promise((resolve) => probe.close(resolve));
    }
  }
}

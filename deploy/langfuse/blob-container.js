// Makes Langfuse's blob container in Azurite, which Langfuse does not make itself. Azurite has no
// tool for it in its image, so this signs one request with the account key. Safe to run again.
const crypto = require("node:crypto");
const http = require("node:http");

const account = "devstoreaccount1";
const key = Buffer.from(process.env.AZURITE_KEY, "base64");
const container = process.env.CONTAINER || "langfuse";

function createContainer() {
  const date = new Date().toUTCString();
  const version = "2021-12-02";
  const toSign = [
    "PUT", "", "", "", "", "", "", "", "", "", "", "",
    `x-ms-date:${date}\nx-ms-version:${version}`,
    `/${account}/${account}/${container}\nrestype:container`,
  ].join("\n");
  const signature = crypto.createHmac("sha256", key).update(toSign, "utf8").digest("base64");
  const request = http.request(
    {
      host: "127.0.0.1",
      port: 10000,
      method: "PUT",
      path: `/${account}/${container}?restype=container`,
      headers: {
        "x-ms-date": date,
        "x-ms-version": version,
        Authorization: `SharedKey ${account}:${signature}`,
        "Content-Length": 0,
      },
    },
    (response) => {
      response.resume();
      // 201 made it, 409 it was there already.
      if (response.statusCode === 201 || response.statusCode === 409) {
        console.log(`blob container ${container}: ${response.statusCode}`);
        return;
      }
      console.error(`blob container ${container}: ${response.statusCode}, trying again`);
      setTimeout(createContainer, 2000);
    },
  );
  request.on("error", () => setTimeout(createContainer, 1000));
  request.end();
}

createContainer();

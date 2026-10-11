import { main } from "./cli/main.js";

main(process.argv.slice(2)).then(
  (code) => {
    process.exitCode = code;
  },
  (err: unknown) => {
    process.stderr.write(`${String(err)}\n`);
    process.exitCode = 2;
  },
);

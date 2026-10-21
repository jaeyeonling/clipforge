// 껍데기 로그: 콘솔과 userData/shell.log 에 함께 쓴다.
"use strict";
const fs = require("node:fs");

let stream = null;

function openLog(file) {
  stream = fs.createWriteStream(file, { flags: "a" });
}

function log(line) {
  const msg = `${new Date().toISOString()} ${line}`;
  console.log(msg);
  try {
    stream?.write(msg + "\n");
  } catch {
    /* 로그를 못 써도 앱은 계속 */
  }
}

module.exports = { log, openLog };

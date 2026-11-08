const test = require("node:test");
const assert = require("node:assert/strict");
const { analyze } = require("../analysis.js");

test("summarizes participants, topics, and messages", () => {
  const result = analyze("林：周五交付\n周：我负责测试进度");

  assert.equal(result.messageCount, 2);
  assert.equal(result.participantCount, 2);
  assert.deepEqual(result.participants, ["林", "周"]);
  assert.deepEqual(result.topics, ["时间与进度", "责任与分工"]);
  assert.equal(result.findings.length, 0);
});

test("flags and masks personal contact information", () => {
  const result = analyze("小王：请联系 13812345678 或 user@example.com");

  assert.equal(result.findings.length, 2);
  assert.ok(result.findings.every((finding) => finding.level === "high"));
  assert.equal(result.findings[0].evidence, "[手机号已隐藏]");
  assert.equal(result.findings[1].evidence, "[邮箱已隐藏]");
  assert.equal(result.status, "需要优先关注");
});

test("flags personal attacks and claims that need evidence", () => {
  const result = analyze("Alex: You're an idiot.\n小林：这个方案肯定是正确的。");

  assert.deepEqual(
    result.findings.map((finding) => [finding.category, finding.level]),
    [["人身攻击", "medium"], ["未经核实的断言", "low"]],
  );
  assert.equal(result.status, "建议进一步核对");
});

test("handles empty input and masks sensitive details in summaries", () => {
  assert.equal(analyze(" \n ").messageCount, 0);
  const result = analyze("小张：我的邮箱是 user@example.com");

  assert.equal(result.summary[0].text, "我的邮箱是 [邮箱已隐藏]");
  assert.equal(result.findings[0].evidence, "[邮箱已隐藏]");
});

const sampleDiscussion = `林：我们原定周五交付，测试还没完成，可能需要延期到下周一。
周：我来跟进测试，今天下班前给出进度和剩余问题。
林：这个方案肯定是正确的，不用再验证了。
周：先补充测试数据和来源，我们再一起确认。`;

const form = document.querySelector("#discussion-form");
const input = document.querySelector("#discussion-input");
const sampleButton = document.querySelector("#load-sample");
const results = document.querySelector("#results");
const emptyState = document.querySelector("#empty-state");

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function renderResults(result) {
  results.replaceChildren();
  emptyState.hidden = true;
  results.hidden = false;

  if (result.messageCount === 0) {
    results.append(createElement("p", "inline-message", "请先粘贴一段讨论内容。"));
    return;
  }

  const highCount = result.findings.filter((finding) => finding.level === "high").length;
  const mediumCount = result.findings.filter((finding) => finding.level === "medium").length;
  const lowCount = result.findings.filter((finding) => finding.level === "low").length;
  const overview = createElement("section", "overview-card");
  overview.setAttribute("aria-labelledby", "overview-title");
  overview.append(createElement("h2", "section-title", "讨论概览"));

  const status = createElement(
    "p",
    `status-banner ${highCount ? "status-high" : result.findings.length ? "status-caution" : "status-safe"}`,
    result.status,
  );
  overview.append(status);

  const metrics = createElement("div", "metrics");
  [
    [result.messageCount, "条发言"],
    [result.participantCount, "位参与者"],
    [result.findings.length, "项风险提示"],
  ].forEach(([value, label]) => {
    const metric = createElement("div", "metric");
    metric.append(createElement("strong", "", String(value)), createElement("span", "", label));
    metrics.append(metric);
  });
  overview.append(metrics);

  const participants = createElement(
    "p",
    "detail-line",
    `参与者：${result.participants.join("、")}`,
  );
  overview.append(participants);
  const topics = createElement(
    "p",
    "detail-line",
    `讨论焦点：${result.topics.length ? result.topics.join("、") : "暂未识别"}`,
  );
  overview.append(topics);

  const summary = createElement("div", "summary-block");
  summary.append(createElement("h3", "subsection-title", "内容摘要"));
  const summaryList = createElement("ul", "summary-list");
  result.summary.forEach((item) => {
    const line = createElement("li");
    line.append(createElement("strong", "", `${item.speaker}：`));
    line.append(document.createTextNode(item.text));
    summaryList.append(line);
  });
  if (result.messageCount > result.summary.length) {
    summaryList.append(
      createElement("li", "muted", `另有 ${result.messageCount - result.summary.length} 条发言未列出`),
    );
  }
  summary.append(summaryList);
  overview.append(summary);
  results.append(overview);

  const riskSection = createElement("section", "risk-section");
  riskSection.setAttribute("aria-labelledby", "risk-title");
  const riskHeading = createElement("div", "risk-heading");
  riskHeading.append(createElement("h2", "section-title", "潜在风险"));
  const counts = createElement(
    "p",
    "risk-counts",
    `高 ${highCount} · 中 ${mediumCount} · 提醒 ${lowCount}`,
  );
  riskHeading.append(counts);
  riskSection.append(riskHeading);

  if (result.findings.length === 0) {
    riskSection.append(
      createElement("p", "no-risks", "当前规则没有识别到明显风险。仍建议结合语境人工判断。"),
    );
  } else {
    result.findings.forEach((finding) => {
      const card = createElement("article", `risk-card risk-${finding.level}`);
      const top = createElement("div", "risk-card-top");
      const levelLabel = { high: "高风险", medium: "中风险", low: "核实提醒" }[finding.level];
      top.append(
        createElement("span", "risk-category", finding.category),
        createElement("span", "risk-level", levelLabel),
      );
      card.append(top);
      card.append(createElement("p", "evidence", `“${finding.evidence}”`));
      card.append(createElement("p", "risk-description", finding.description));
      card.append(createElement("p", "risk-action", `建议：${finding.action}`));
      card.append(createElement("p", "risk-source", `${finding.speaker} · 第 ${finding.line} 条发言`));
      riskSection.append(card);
    });
  }
  results.append(riskSection);
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  renderResults(window.DiscussionAnalyzer.analyze(input.value));
});

sampleButton.addEventListener("click", () => {
  input.value = sampleDiscussion;
  input.focus();
});

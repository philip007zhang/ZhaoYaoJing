(function (root, factory) {
  const analyzer = factory();

  if (typeof module !== "undefined" && module.exports) {
    module.exports = analyzer;
  } else {
    root.DiscussionAnalyzer = analyzer;
  }
})(typeof globalThis === "undefined" ? this : globalThis, function () {
  const riskRules = [
    {
      category: "隐私信息",
      level: "high",
      pattern: /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|\b1[3-9]\d{9}\b/i,
      description: "内容中可能包含邮箱或手机号，公开分享前建议先脱敏。",
      action: "隐藏或删除联系方式，并确认是否获得当事人同意。",
      mask: (text) =>
        text
          .replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, "[邮箱已隐藏]")
          .replace(/\b1[3-9]\d{9}\b/g, "[手机号已隐藏]"),
    },
    {
      category: "人身攻击",
      level: "medium",
      pattern: /废物|蠢货|白痴|滚开|没脑子|you(?:'re| are) (?:an? )?(?:idiot|stupid|moron)|shut up/i,
      description: "出现针对个人的贬损或攻击性措辞，可能让讨论升级。",
      action: "聚焦具体行为或事实，避免评价参与者本人。",
    },
    {
      category: "威胁性表达",
      level: "high",
      pattern: /弄死你|杀了你|让你付出代价|我要报复你|i(?:'ll| will) (?:kill|hurt) you|you(?:'ll| will) pay for this/i,
      description: "出现可能被理解为威胁的表达，建议优先确认当事人安全。",
      action: "暂停对话并联系适当的安全或管理支持。",
    },
    {
      category: "未经核实的断言",
      level: "low",
      pattern: /肯定是|百分之百|100%|毫无疑问|显然就是|绝对不可能|definitely|100 percent|without a doubt/i,
      description: "出现强确定性表述，但仅凭文本无法核实其依据。",
      action: "补充来源或证据，并将事实与推测分开表达。",
    },
  ];

  const topics = [
    { name: "时间与进度", pattern: /时间|日期|截止|进度|延期|交付|schedule|deadline|timeline|delay/i },
    { name: "责任与分工", pattern: /负责|责任|分工|跟进|owner|ownership|responsib|assign/i },
    { name: "预算与资源", pattern: /预算|费用|成本|资源|经费|budget|cost|resource/i },
    { name: "方案与决策", pattern: /方案|决定|选择|计划|优先级|proposal|decision|plan|option/i },
    { name: "证据与信息", pattern: /数据|证据|来源|确认|验证|事实|data|evidence|source|verify|confirm/i },
  ];

  function maskSensitiveText(text) {
    return text
      .replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, "[邮箱已隐藏]")
      .replace(/\b1[3-9]\d{9}\b/g, "[手机号已隐藏]");
  }

  function parseMessages(input) {
    return input
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line, index) => {
        const match = line.match(/^([^:：]{1,30})[:：]\s*(.+)$/);
        return {
          speaker: match ? match[1].trim() : `发言 ${index + 1}`,
          text: match ? match[2].trim() : line,
        };
      });
  }

  function analyze(input) {
    const messages = parseMessages(String(input || ""));
    const speakers = [...new Set(messages.map((message) => message.speaker))];
    const findings = [];

    messages.forEach((message, index) => {
      riskRules.forEach((rule) => {
        const mask = rule.mask || maskSensitiveText;
        const pattern = new RegExp(
          rule.pattern.source,
          rule.pattern.flags.includes("g") ? rule.pattern.flags : `${rule.pattern.flags}g`,
        );
        for (const match of message.text.matchAll(pattern)) {
          findings.push({
            category: rule.category,
            level: rule.level,
            speaker: message.speaker,
            line: index + 1,
            evidence: mask(match[0]),
            description: rule.description,
            action: rule.action,
          });
        }
      });
    });

    const matchedTopics = topics
      .filter((topic) => messages.some((message) => topic.pattern.test(message.text)))
      .map((topic) => topic.name);
    const summary = messages.slice(0, 3).map((message) => ({
      speaker: message.speaker,
      text: maskSensitiveText(
        message.text.length > 100 ? `${message.text.slice(0, 100)}…` : message.text,
      ),
    }));
    const highRisks = findings.filter((finding) => finding.level === "high").length;
    const status = highRisks
      ? "需要优先关注"
      : findings.length
        ? "建议进一步核对"
        : "暂未发现明显风险";

    return {
      messageCount: messages.length,
      participantCount: speakers.length,
      participants: speakers,
      topics: matchedTopics,
      summary,
      findings,
      status,
    };
  }

  return { analyze };
});

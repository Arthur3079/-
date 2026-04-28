function opsConsole() {
  const ok = (label) => ({ label, tone: "ok" });
  const warn = (label) => ({ label, tone: "warn" });
  const danger = (label) => ({ label, tone: "danger" });
  const info = (label) => ({ label, tone: "info" });

  const accounts = [
    {
      name: "sonya-main",
      owner: "RU Growth Team",
      state: ok("online"),
      telegram: "Connected",
      runtime: "Healthy",
      llm: "OpenAI primary",
      payments: "Stars + retries ok",
      scheduler: "Running",
      safety: "Nominal",
    },
    {
      name: "sonya-eu",
      owner: "EU Ops",
      state: warn("degraded"),
      telegram: "Slow API",
      runtime: "Queue lag",
      llm: "Fallback model",
      payments: "2 failed callbacks",
      scheduler: "Behind 14m",
      safety: "Nominal",
    },
    {
      name: "sonya-backup",
      owner: "Night shift",
      state: danger("offline"),
      telegram: "Disconnected",
      runtime: "Stopped",
      llm: "No traffic",
      payments: "No events",
      scheduler: "Disabled",
      safety: "Unknown",
    },
  ];

  return {
    tab: "operations",
    nav: [
      { id: "operations", label: "Центр операций", count: "14" },
      { id: "accounts", label: "Аккаунты" },
      { id: "inbox", label: "Диалоги", count: "6" },
      { id: "fans", label: "Фаны CRM" },
      { id: "revenue", label: "Выручка" },
      { id: "offers", label: "Офферы" },
      { id: "followups", label: "Follow-ups", count: "21" },
      { id: "safety", label: "Safety" },
      { id: "runtime", label: "Runtime" },
      { id: "settings", label: "Настройки" },
    ],
    systemState: { ok: true },
    accounts,
    selectedAccount: accounts[0],
    accountHealth: [
      { account: "sonya-main", telegram: ok("online"), runtime: ok("healthy"), llm: ok("stable"), payments: warn("2 retries"), scheduler: ok("on time"), safety: ok("clear"), event: "offer_sent fan#934" },
      { account: "sonya-eu", telegram: warn("degraded"), runtime: warn("lag 180s"), llm: ok("fallback active"), payments: danger("callback errors"), scheduler: warn("14 overdue"), safety: ok("clear"), event: "payment_timeout #411" },
      { account: "sonya-backup", telegram: danger("offline"), runtime: danger("stopped"), llm: info("idle"), payments: info("no flow"), scheduler: info("not running"), safety: warn("not checked"), event: "Нет событий за период" },
    ],
    priorityQueue: [
      { priority: danger("P1"), account: "sonya-main", fan: "@mila_rose", process: "Payment", signal: "Payment attempts x3", risk: warn("medium"), sla: "07m", next: "manual handoff" },
      { priority: warn("P2"), account: "sonya-eu", fan: "@venus_ava", process: "Offer", signal: "Готов к офферу", risk: info("low"), sla: "18m", next: "send bundle" },
      { priority: warn("P2"), account: "sonya-main", fan: "@neo_fan", process: "Follow-ups", signal: "Просрочено 3h", risk: warn("medium"), sla: "22m", next: "resume cadence" },
    ],
    kpi: {
      conversation: [
        { label: "Требует ответа", value: "14" },
        { label: "Avg response time", value: "02:42" },
        { label: "SLA overdue", value: "5" },
        { label: "Inbound / outbound", value: "212 / 346" },
      ],
      pipeline: [
        { label: "Welcome", value: "48" },
        { label: "Warmup", value: "67" },
        { label: "Qualify", value: "39" },
        { label: "Offer pending", value: "22" },
        { label: "Aftercare", value: "18" },
        { label: "Repeat ready", value: "24" },
        { label: "Ghost", value: "31" },
      ],
      revenue: [
        { label: "Offers sent", value: "83" },
        { label: "Payment attempts", value: "92" },
        { label: "Purchases", value: "28" },
        { label: "Revenue", value: "$3,840" },
        { label: "Failed / refunded", value: "11" },
      ],
      safety: [
        { label: "Safety blocks", value: "0" },
        { label: "Handoff", value: "1" },
        { label: "Suppression", value: "2" },
        { label: "Risky dialogues", value: "1" },
      ],
      runtime: [
        { label: "Last event", value: "12:44:11" },
        { label: "LLM errors", value: "3" },
        { label: "Telegram errors", value: "4" },
        { label: "Scheduler due", value: "42" },
        { label: "Payment bot errors", value: "2" },
      ],
    },
    chats: [
      { fan: "@mila_rose", signal: "Оффер не отправлен", waiting: true, stage: "qualify", risk: "medium", readiness: "high", ltv: "$420" },
      { fan: "@venus_ava", signal: "Готов к офферу", waiting: false, stage: "offer_pending", risk: "low", readiness: "high", ltv: "$780" },
      { fan: "@neo_fan", signal: "Просрочено follow-up", waiting: true, stage: "warmup", risk: "medium", readiness: "medium", ltv: "$110" },
    ],
    selectedChat: null,
    init() {
      this.selectedChat = this.chats[0];
    },
    currentLabel() {
      return this.nav.find((x) => x.id === this.tab)?.label || "";
    },
  };
}

document.addEventListener("alpine:init", () => {
  Alpine.data("opsConsole", opsConsole);
});

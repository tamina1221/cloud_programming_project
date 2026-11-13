// MoneyPlan 화면 (N07, C21). API를 호출하고 응답을 보여줄 뿐 금액을 계산하지 않는다 (합계 표시용 덧셈 제외).

const $ = (sel) => document.querySelector(sel);

const LABELS = {
  incomeType: { salary: "급여", allowance: "용돈", etc: "기타" },
  planStatus: { ok: "정상", partial: "부분 배분", infeasible: "배분 불가" },
  goalStatus: {
    full: "충족", short: "부족", will_miss: "목표 미달 예정",
    achieved: "목표 달성", period_error: "목표 기간 오류",
  },
  category: { fixed: "고정 지출", living: "생활비" },
  field: {  // 422 오류의 loc → 한국어 이름 (N05)
    amount: "금액", income_type: "유형", income_date: "날짜", memo: "메모",
    expense_name: "항목명", month: "월", min_living: "최소 생활비",
    goal_name: "목표명", target_amount: "목표 금액", current_amount: "현재 확보액",
    target_month: "목표 월", priority: "우선순위",
    category: "목적", goal_id: "목표", expense_date: "날짜", deposit_date: "날짜",
    items: "배분 항목", allocation_id: "배분 항목", allocated_amount: "배분 금액", mode: "방식",
  },
};

const won = (n) => (n ?? 0).toLocaleString("ko-KR") + "원";
const month = () => $("#month").value;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const toInt = (v) => (v === "" || v == null ? null : Number(v));

let currentTab = "input";

// ---------- API 호출과 오류 표시 ----------

class ApiError extends Error {
  constructor(status, data) {
    super(typeof data?.detail === "string" ? data.detail : `HTTP ${status}`);
    this.status = status;
    this.data = data;
  }
}

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

function errorText(err) {
  // 422: detail 배열의 msg를 "입력값을 확인하세요: 금액 - 0보다 커야 합니다." 형태로
  if (err instanceof ApiError && err.status === 422 && Array.isArray(err.data?.detail)) {
    const parts = err.data.detail.map((d) => {
      const key = [...(d.loc || [])].reverse().find((k) => typeof k === "string" && k !== "body");
      const label = LABELS.field[key];
      return label ? `${label} - ${d.msg}` : d.msg;
    });
    return "입력값을 확인하세요: " + parts.join(" / ");
  }
  return err.message || String(err);
}

function showError(err) {
  const box = $("#alert");
  box.textContent = errorText(err);
  box.hidden = false;
}

function clearError() {
  $("#alert").hidden = true;
  $("#alert").textContent = "";
}

// 버튼·폼 동작 공통: 오류를 지우고 실행, 실패하면 상단에 표시
async function run(fn) {
  clearError();
  try {
    await fn();
  } catch (err) {
    showError(err);
  }
}

function badge(status) {
  return `<span class="badge ${status}">${LABELS.planStatus[status]}</span>`;
}

// ---------- 등록·수정 폼 공통 ----------

// 폼 값 → 요청 본문. 숫자 입력칸은 정수로 바꾼다.
function formBody(form) {
  const body = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "number") body[el.name] = toInt(el.value);
    else if (el.name === "memo") body[el.name] = el.value || null;
    else body[el.name] = el.value;
  }
  return body;
}

function defaultDate() {
  return `${month()}-01`;
}

function resetForm(form) {
  form.reset();
  delete form.dataset.editId;
  const submit = form.querySelector('button[type="submit"]');
  submit.dataset.label ??= submit.textContent;  // 원래 버튼 이름(등록·저장)으로 되돌림
  submit.textContent = submit.dataset.label;
  const cancel = form.querySelector(".cancel");
  if (cancel) cancel.hidden = true;
  form.querySelectorAll('input[type="date"]').forEach((el) => { el.value = defaultDate(); });
}

function startEdit(form, values) {
  for (const [name, value] of Object.entries(values)) {
    if (form.elements[name]) form.elements[name].value = value ?? "";
  }
  form.dataset.editId = values.id;
  form.querySelector('button[type="submit"]').textContent = "수정 저장";
  form.querySelector(".cancel").hidden = false;
  form.scrollIntoView({ block: "nearest" });
}

// 등록(POST)과 수정(PUT /{id})을 같은 폼으로 처리한다.
function bindForm(form, path, toBody, after) {
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    run(async () => {
      const id = form.dataset.editId;
      const data = id
        ? await api("PUT", `${path}/${id}`, toBody(form))
        : await api("POST", path, toBody(form));
      resetForm(form);
      if (after) after(data);
      await loadTab();
    });
  });
  const cancel = form.querySelector(".cancel");
  if (cancel) cancel.addEventListener("click", () => resetForm(form));
}

function remove(path) {
  run(async () => {
    await api("DELETE", path);  // confirm 창 없이 바로 삭제
    await loadTab();
  });
}

// 표의 [수정] 버튼(data-edit="id")을 누르면 그 행 값으로 폼을 수정 모드로 바꾼다.
function bindEditButtons(tbody, items, form, toValues = (x) => x) {
  tbody.querySelectorAll("[data-edit]").forEach((btn) => {
    const item = items.find((x) => x.id === Number(btn.dataset.edit));
    btn.addEventListener("click", () => startEdit(form, toValues(item)));
  });
}

// 조회 결과가 404(아직 설정·계획이 없음)면 null을 돌려준다.
async function getOrNull(path) {
  try {
    return await api("GET", path);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

const sumAmount = (list) => won(list.reduce((s, x) => s + x.amount, 0));  // 합계 표시용 덧셈

// ---------- 1. 입력 탭 (R01~R04) ----------

async function loadInput() {
  const m = month();
  const [incomes, fixed, goals] = await Promise.all([
    api("GET", `/incomes?month=${m}`),
    api("GET", `/fixed-expenses?month=${m}`),
    api("GET", "/goals"),
  ]);

  $("#incomeRows").innerHTML = incomes.map((i) => `
    <tr>
      <td>${esc(i.income_date)}</td>
      <td>${LABELS.incomeType[i.income_type]}</td>
      <td class="num">${won(i.amount)}</td>
      <td>${esc(i.memo)}</td>
      <td><button type="button" data-edit="${i.id}">수정</button>
          <button type="button" data-del="/incomes/${i.id}">삭제</button></td>
    </tr>`).join("");
  $("#incomeTotal").textContent = sumAmount(incomes);
  bindEditButtons($("#incomeRows"), incomes, $("#incomeForm"));

  $("#fixedRows").innerHTML = fixed.map((f) => `
    <tr>
      <td>${esc(f.expense_name)}</td>
      <td class="num">${won(f.amount)}</td>
      <td><button type="button" data-edit="${f.id}">수정</button>
          <button type="button" data-del="/fixed-expenses/${f.id}">삭제</button></td>
    </tr>`).join("");
  $("#fixedTotal").textContent = sumAmount(fixed);
  bindEditButtons($("#fixedRows"), fixed, $("#fixedForm"));

  const setting = await getOrNull(`/settings/${m}`);
  $("#settingNow").textContent = setting ? won(setting.min_living) : "아직 설정하지 않았습니다";

  $("#goalRows").innerHTML = goals.map((g) => `
    <tr>
      <td>${g.priority}</td>
      <td>${esc(g.goal_name)}</td>
      <td class="num">${won(g.target_amount)}</td>
      <td class="num">${won(g.current_amount)}</td>
      <td>${esc(g.target_month)}</td>
      <td><button type="button" data-edit="${g.id}">수정</button>
          <button type="button" data-del="/goals/${g.id}">삭제</button></td>
    </tr>`).join("");
  bindEditButtons($("#goalRows"), goals, $("#goalForm"));
}

bindForm($("#incomeForm"), "/incomes", formBody);
bindForm($("#fixedForm"), "/fixed-expenses", (f) => ({ ...formBody(f), month: month() }));
bindForm($("#goalForm"), "/goals", formBody);

$("#settingForm").addEventListener("submit", (e) => {
  e.preventDefault();
  run(async () => {
    await api("PUT", `/settings/${month()}`, formBody(e.target));
    e.target.reset();
    await loadTab();
  });
});

// ---------- 2. 배분 탭 (R05~R09) ----------

function itemName(a, plan) {
  if (a.category !== "goal") return LABELS.category[a.category];
  const g = plan.goals.find((x) => x.goal_id === a.goal_id);
  return g ? g.name : `목표 ${a.goal_id}`;
}

function planMessages(plan) {
  if (plan.status === "infeasible") {
    const subject = plan.shortage_target === "fixed" ? "고정 지출이" : "최소 생활비가";
    return [`${subject} ${won(plan.shortage)} 부족합니다.`];
  }
  return plan.goals.flatMap((g) => {
    if (g.status === "short") {
      return [`${g.name} 목표가 ${won(g.lacking)} 부족합니다. 다음 달에는 ${won(g.next_required)}이 필요합니다.`];
    }
    if (g.status === "will_miss") {
      return [`${g.name} 목표가 ${won(g.lacking)} 부족합니다. 이번 달이 목표 월이라 목표를 달성하지 못합니다.`];
    }
    if (g.status === "period_error") {
      return [`${g.name} 목표의 목표 월이 지났습니다. 목표를 수정하세요.`];
    }
    return [];
  });
}

// previous가 있으면 "이전 배분" 열을 회색으로 나란히 보여준다 (5.5).
function renderPlan(plan, previous) {
  $("#planEmpty").hidden = true;
  $("#planBody").hidden = false;
  $("#planError").textContent = "";
  $("#planBadge").innerHTML = badge(plan.status);
  $("#planMessages").innerHTML = planMessages(plan).map((t) => `<p>${esc(t)}</p>`).join("");

  const prevAmount = (a) => {
    const p = previous?.allocations.find((x) => x.category === a.category && x.goal_id === a.goal_id);
    return p ? won(p.allocated_amount) : "-";
  };
  const locked = plan.status === "infeasible";

  $("#planHead").innerHTML = `<tr><th>항목</th><th class="num">필요 금액</th>
    ${previous ? '<th class="num prev">이전 배분</th>' : ""}
    <th class="num">배분 금액</th><th>목표 상태</th><th class="num">다음 달 필요 적립액</th></tr>`;

  $("#planRows").innerHTML = plan.allocations.map((a) => `
    <tr>
      <td>${esc(itemName(a, plan))}${a.is_manual ? ' <span class="muted">(수정함)</span>' : ""}</td>
      <td class="num">${won(a.required_amount)}</td>
      ${previous ? `<td class="num prev">${prevAmount(a)}</td>` : ""}
      <td class="num">${a.category === "goal"
        ? `<input type="number" min="0" step="1" data-alloc="${a.id}" value="${a.allocated_amount}"${locked ? " disabled" : ""}>`
        : won(a.allocated_amount)}</td>
      <td>${a.goal_status ? LABELS.goalStatus[a.goal_status] : ""}</td>
      <td class="num">${a.next_required != null ? won(a.next_required) : ""}</td>
    </tr>`).join("");

  $("#planIncome").textContent = won(plan.total_income);
  $("#planAllocated").textContent = won(plan.total_allocated);
  $("#planUnallocated").textContent = won(plan.unallocated);
  $("#btnSave").disabled = locked || !plan.allocations.some((a) => a.category === "goal");
}

function renderNoPlan() {
  $("#planBadge").innerHTML = "";
  $("#planMessages").innerHTML = "";
  $("#planBody").hidden = true;
  $("#planEmpty").hidden = false;
}

async function loadPlan() {
  const plan = await getOrNull(`/plans/${month()}`);
  if (plan) renderPlan(plan, null);
  else renderNoPlan();
}

function allocate(mode) {
  run(async () => {
    const res = await api("POST", `/plans/${month()}/allocate?mode=${mode}`);
    renderPlan(res.current, res.previous);
  });
}

$("#btnAllocate").addEventListener("click", () => allocate("reallocate"));
$("#btnKeep").addEventListener("click", () => allocate("keep"));

$("#btnSave").addEventListener("click", async () => {
  clearError();
  $("#planError").textContent = "";
  const items = [...document.querySelectorAll("[data-alloc]")].map((el) => ({
    allocation_id: Number(el.dataset.alloc),
    allocated_amount: toInt(el.value),
  }));
  try {
    renderPlan(await api("PUT", `/plans/${month()}/allocations`, { items }), null);
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) {  // AT08, T14, T17: 빨간 글씨로
      const excess = err.data?.excess != null ? ` (초과 금액 ${won(err.data.excess)})` : "";
      $("#planError").textContent = err.message + excess;
    } else {
      showError(err);
    }
  }
});

// ---------- 3. 소비 탭 (R10~R11) ----------

function purposeName(e, goals) {
  if (e.category !== "goal") return LABELS.category[e.category];
  const g = goals.find((x) => x.id === e.goal_id);
  return g ? g.goal_name : `목표 ${e.goal_id}`;
}

function purposeValue(e) {
  return e.category === "goal" ? `goal:${e.goal_id}` : e.category;
}

function expenseBody(form) {
  const body = formBody(form);
  const [category, goalId] = body.purpose.split(":");
  delete body.purpose;
  return { ...body, category, goal_id: goalId ? Number(goalId) : null };
}

function showBalance(res) {
  const b = res.balance;
  $("#expenseBalance").innerHTML = `${esc(b.name)} 잔액: <span class="${b.balance < 0 ? "negative" : ""}">${won(b.balance)}</span>`
    + (b.is_over ? ' <strong class="negative">초과 소비</strong>' : "");
}

async function loadExpense() {
  const [expenses, goals, deposits] = await Promise.all([
    api("GET", `/expenses?month=${month()}`),
    api("GET", "/goals"),
    api("GET", `/goal-deposits?month=${month()}`),
  ]);

  // 소비 목적은 고정 지출·생활비만 (C31). 목표에 모은 돈은 아래 "목표 확보 등록"으로 따로 기록한다.
  const select = $("#expensePurpose");
  const selected = select.value;
  select.innerHTML = `<option value="fixed">고정 지출</option><option value="living">생활비</option>`;
  select.value = selected === "fixed" ? "fixed" : "living";

  // 예전에 목표 목적으로 등록한 소비는 목록에 보여주고 삭제만 할 수 있게 한다.
  $("#expenseRows").innerHTML = expenses.map((e) => `
    <tr>
      <td>${esc(e.expense_date)}</td>
      <td>${esc(purposeName(e, goals))}</td>
      <td class="num">${won(e.amount)}</td>
      <td>${esc(e.memo)}</td>
      <td>${e.category === "goal" ? "" : `<button type="button" data-edit="${e.id}">수정</button>`}
          <button type="button" data-del="/expenses/${e.id}">삭제</button></td>
    </tr>`).join("");
  bindEditButtons($("#expenseRows"), expenses, $("#expenseForm"), (e) => ({ ...e, purpose: purposeValue(e) }));

  // 목표 확보 등록 (C31): 목표 선택 목록
  const secure = $("#secureGoal");
  const secureSelected = secure.value;
  secure.innerHTML = goals.length
    ? goals.map((g) => `<option value="${g.id}">${esc(g.goal_name)}</option>`).join("")
    : '<option value="" disabled selected>등록된 목표가 없습니다</option>';
  if ([...secure.options].some((o) => o.value === secureSelected)) secure.value = secureSelected;
  $("#secureForm").querySelector('button[type="submit"]').disabled = goals.length === 0;

  // 확보 내역 (그 달). 삭제하면 현재 확보액에서 다시 뺀다.
  $("#depositRows").innerHTML = deposits.map((d) => `
    <tr>
      <td>${esc(d.deposit_date)}</td>
      <td>${esc(goals.find((g) => g.id === d.goal_id)?.goal_name ?? `목표 ${d.goal_id}`)}</td>
      <td class="num">${won(d.amount)}</td>
      <td><button type="button" data-del="/goal-deposits/${d.id}">삭제</button></td>
    </tr>`).join("");
}

bindForm($("#expenseForm"), "/expenses", expenseBody, showBalance);

// 목표 확보 등록 (C31, T20): 확보 기록을 남기고 모은 금액을 현재 확보액에 더한다.
$("#secureForm").addEventListener("submit", (e) => {
  e.preventDefault();
  run(async () => {
    const form = e.target;
    const goalId = form.elements.goal_id.value;
    const { goal } = await api("POST", "/goal-deposits", { ...formBody(form), goal_id: Number(goalId) });
    resetForm(form);
    form.elements.goal_id.value = goalId;
    $("#secureResult").textContent =
      `${goal.goal_name} 현재 확보액: ${won(goal.current_amount)} / ${won(goal.target_amount)}`;
    await loadTab();
  });
});

// ---------- 4. 대시보드 탭 (R12) ----------

async function loadDashboard() {
  const d = await api("GET", `/dashboard/${month()}`);
  $("#dashIncome").textContent = won(d.total_income);
  $("#dashBadge").innerHTML = d.plan ? badge(d.plan.status) : "";
  $("#dashNoPlan").hidden = d.plan !== null;  // U07
  $("#dashWarning").hidden = !d.plan || d.plan.total_income === d.total_income;  // U03

  $("#balanceRows").innerHTML = d.balances.map((b) => `
    <tr>
      <td>${esc(b.name)}</td>
      <td class="num">${won(b.allocated)}</td>
      <td class="num">${won(b.spent)}</td>
      <td class="num ${b.balance < 0 ? "negative" : ""}">${won(b.balance)}${b.is_over ? " (초과 소비)" : ""}</td>
    </tr>`).join("");

  $("#goalBars").innerHTML = d.goals.map((g) => `
    <div class="bar-row">
      <span>${esc(g.goal_name)}</span>
      <div class="bar"><div style="width:${Math.min(g.achievement_rate, 100)}%"></div></div>
      <span class="num">${g.achievement_rate}% (${won(g.secured_amount)} / ${won(g.target_amount)})</span>
    </div>`).join("") || '<p class="muted">등록된 목표가 없습니다.</p>';
}

// ---------- 탭·월 전환 ----------

const LOADERS = { input: loadInput, plan: loadPlan, expense: loadExpense, dashboard: loadDashboard };

async function loadTab() {
  await LOADERS[currentTab]();
}

document.querySelectorAll(".tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    currentTab = btn.dataset.tab;
    document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".tab").forEach((s) => { s.hidden = s.id !== `tab-${currentTab}`; });
    $("#expenseBalance").innerHTML = "";
    $("#secureResult").textContent = "";
    run(loadTab);
  });
});

$("#month").addEventListener("change", () => {
  if (!month()) return;
  document.querySelectorAll("form").forEach(resetForm);
  $("#expenseBalance").innerHTML = "";
  $("#secureResult").textContent = "";
  run(loadTab);
});

// 삭제 버튼은 표가 다시 그려져도 동작하도록 위임으로 처리한다.
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-del]");
  if (btn) remove(btn.dataset.del);
});

document.querySelectorAll("form").forEach(resetForm);
run(loadTab);

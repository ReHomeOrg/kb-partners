import "server-only";

import { apiFetch, type ApiFetchDeps } from "@/lib/api/transport";
import type { components, operations } from "@/lib/api/schema";

/** RFC 7807 problem+json (контракт `components.schemas.Error`). */
export type Problem = components["schemas"]["Error"];

// problem хранится в WeakMap — не сериализуется JSON.stringify, не утекает в логи (ФЗ-152).
const problems = new WeakMap<ApiError, Problem>();

/**
 * Ошибка вызова API kb-partners. `message` — только `status`+`title` (без `detail`,
 * где возможны ПДн). Полный `problem` доступен через геттер для UI.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly title: string;

  constructor(status: number, title: string, problem?: Problem) {
    super(`${status} ${title}`);
    this.name = "ApiError";
    this.status = status;
    this.title = title;
    if (problem) {
      problems.set(this, problem);
    }
  }

  get problem(): Problem | undefined {
    return problems.get(this);
  }
}

type JsonOf<T> = T extends { content: { "application/json": infer B } } ? B : never;
type OkJson<O extends keyof operations, S extends keyof operations[O]["responses"]> = JsonOf<
  operations[O]["responses"][S]
>;
type BodyJson<O extends keyof operations> = operations[O] extends {
  requestBody?: { content: { "application/json": infer B } };
}
  ? B
  : never;

export type RequestListResponse = OkJson<"listRequests", 200>;
export type RequestDetail = OkJson<"getRequest", 200>;
export type MessageList = OkJson<"listRequestMessages", 200>;
export type MessageRead = OkJson<"addRequestMessage", 201>;
export type PartnerResponseInput = BodyJson<"partnerResponse">;
export type ListRequestsQuery = NonNullable<operations["listRequests"]["parameters"]["query"]>;
// Операторские действия (рабочее место оператора, E2/E3/E4/E7/E9).
export type TransitionInput = BodyJson<"transitionRequest">;
export type AssignInput = BodyJson<"assignRequest">;
export type MessageInput = BodyJson<"addRequestMessage">;
export type RequesterContext = OkJson<"getRequesterContext", 200>;

const PREFIX = "/api/v1/partners";

async function readProblem(response: Response): Promise<Problem | undefined> {
  try {
    return (await response.json()) as Problem;
  } catch {
    return undefined;
  }
}

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const problem = await readProblem(response);
    throw new ApiError(response.status, problem?.title ?? response.statusText, problem);
  }
  return (await response.json()) as T;
}

function buildQuery(query: ListRequestsQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) {
      params.set(key, String(value));
    }
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

/** Список заявок партнёра (scope-фильтр на бэкенде). */
export async function listRequests(
  query: ListRequestsQuery = {},
  deps?: ApiFetchDeps,
): Promise<RequestListResponse> {
  const response = await apiFetch(`${PREFIX}/requests${buildQuery(query)}`, {}, deps);
  return parseJson<RequestListResponse>(response);
}

/** Карточка заявки. */
export async function getRequest(id: string, deps?: ApiFetchDeps): Promise<RequestDetail> {
  const response = await apiFetch(`${PREFIX}/requests/${id}`, {}, deps);
  return parseJson<RequestDetail>(response);
}

/** Сообщения по заявке (внутренние партнёру не видны — фильтрует бэкенд). */
export async function listMessages(id: string, deps?: ApiFetchDeps): Promise<MessageList> {
  const response = await apiFetch(`${PREFIX}/requests/${id}/messages`, {}, deps);
  return parseJson<MessageList>(response);
}

/** Ответ партнёра (accepted/rejected/in_progress/done) — портал LIGHT (FR-10.2). */
export async function partnerRespond(
  id: string,
  body: PartnerResponseInput,
  deps?: ApiFetchDeps,
): Promise<RequestDetail> {
  return postJson<RequestDetail>(`${PREFIX}/requests/${id}/partner-response`, body, deps);
}

async function postJson<T>(path: string, body: unknown, deps?: ApiFetchDeps): Promise<T> {
  const response = await apiFetch(
    path,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    },
    deps,
  );
  return parseJson<T>(response);
}

// --- Операторские действия (рабочее место оператора) ---

/** Реклассификация заявки оператором (E2, FR-2.5). */
export async function classifyRequest(id: string, deps?: ApiFetchDeps): Promise<RequestDetail> {
  return postJson<RequestDetail>(`${PREFIX}/requests/${id}/classify`, {}, deps);
}

/** Подбор/назначение партнёра (E3, FR-3.4): авто (пусто) или ручное (partner_id). */
export async function assignRequest(
  id: string,
  body: AssignInput = {},
  deps?: ApiFetchDeps,
): Promise<RequestDetail> {
  return postJson<RequestDetail>(`${PREFIX}/requests/${id}/assign`, body, deps);
}

/** Диспетчеризация по каналу (E4). */
export async function dispatchRequest(id: string, deps?: ApiFetchDeps): Promise<RequestDetail> {
  return postJson<RequestDetail>(`${PREFIX}/requests/${id}/dispatch`, {}, deps);
}

/** Произвольный переход FSM оператором/агентом (§7). */
export async function transitionRequest(
  id: string,
  body: TransitionInput,
  deps?: ApiFetchDeps,
): Promise<RequestDetail> {
  return postJson<RequestDetail>(`${PREFIX}/requests/${id}/transition`, body, deps);
}

/** Добавить сообщение/внутреннюю заметку (is_internal — только оператору, правило 10). */
export async function addMessage(
  id: string,
  body: MessageInput,
  deps?: ApiFetchDeps,
): Promise<MessageRead> {
  return postJson<MessageRead>(`${PREFIX}/requests/${id}/messages`, body, deps);
}

/** Контекст заявителя (E9, ПДн — только оператору/агенту). */
export async function getRequesterContext(
  id: string,
  deps?: ApiFetchDeps,
): Promise<RequesterContext> {
  const response = await apiFetch(`${PREFIX}/requests/${id}/requester-context`, {}, deps);
  return parseJson<RequesterContext>(response);
}

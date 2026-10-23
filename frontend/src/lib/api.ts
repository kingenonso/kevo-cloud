// Helper for the many KEVO endpoints that take plain scalar params rather
// than a Pydantic JSON body - FastAPI treats those as query parameters.
// (Confirmed by reading app.py: LoanRequest, OptionFundingReferral,
// SpvPool/SpvPoolCommitment, ForwardSaleContract, TenderOfferProgram/
// Election/Settlement, LiquidityEventSignal, and most PUT-action
// endpoints all use this style; endpoints with a dedicated
// `*Create`/`*Request` BaseModel - Listing, BuyerInterest,
// InvestorEligibility, Evidence, RofrRequest, SellerFinancing*,
// LiquidityCommitment, SpeedDiscountOffer - take a JSON body instead and
// should keep using apiFetch directly with Content-Type: application/json.)
import { apiFetch } from "@/lib/auth"

export type QueryParams = Record<string, string | number | boolean | null | undefined>

export function toQueryString(params: QueryParams): string {
  const usp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue
    usp.set(key, String(value))
  }
  const qs = usp.toString()
  return qs ? `?${qs}` : ""
}

export async function apiFetchQuery(
  path: string,
  method: "POST" | "PUT" | "DELETE",
  params: QueryParams = {}
): Promise<Response> {
  return apiFetch(`${path}${toQueryString(params)}`, { method })
}

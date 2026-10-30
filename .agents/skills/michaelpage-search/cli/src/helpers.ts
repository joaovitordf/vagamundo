import { createHelpers } from "../../../_portal-kit/src/helpers.js"
export * from "../../../_portal-kit/src/types.js"

const h = createHelpers({
  portal: "a Michael Page",
  ua: "Mozilla/5.0 (compatible; michaelpage-cli/1.0)",
})

export const {
  PORTAL,
  UA,
  writeError,
  httpGet,
  retryAfterMs,
  sleep,
  contractDate,
  brDate,
  relativeDate,
  formatSalary,
  withinJobAge,
  renderTable,
  renderPlain,
  renderSearch,
  renderDetailPlain,
  parseFlags,
  badArg,
  parseIntFlag,
  rejectUnknown,
  rejectEmpty,
  WORKPLACE_LABELS,
  cleanHtml,
  decodeHtmlEntities,
  foldAccents,
  inlineText,
  ldLocation,
  readJobPosting,
  tidyPunctuation,
  titleMatches,
} = h

// New Relic Browser agent (config from the account's generated snippet), on the live site only: local builds
// (make serve) and other hosts report nothing. The loader, nr-loader-spa, comes from js-agent.newrelic.com.
if (location.hostname === "mimir.slackworks.com") {
  window.NREUM || (NREUM = {});
  NREUM.init = {browser_consent_mode: {enabled: false}, privacy: {cookies_enabled: true}, performance: {capture_measures: true},
    ajax: {deny_list: ["bam.nr-data.net"], capture_payloads: "none"}};
  NREUM.loader_config = {accountID: "49251", trustKey: "49251", agentID: "1103549341", licenseKey: "9c55f98e3f",
    applicationID: "1103549341"};
  NREUM.info = {beacon: "bam.nr-data.net", errorBeacon: "bam.nr-data.net", licenseKey: "9c55f98e3f",
    applicationID: "1103549341", sa: 1};
  const s = document.createElement("script");
  s.src = "https://js-agent.newrelic.com/nr-loader-spa-1.323.0.min.js";
  document.head.appendChild(s);
}

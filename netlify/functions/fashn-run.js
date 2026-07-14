const FASHN_API_BASE = "https://api.fashn.ai/v1";

function json(statusCode, body) {
  return {
    statusCode,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
    body: JSON.stringify(body),
  };
}

exports.handler = async function handler(event) {
  if (event.httpMethod !== "POST") {
    return json(405, { message: "Method Not Allowed" });
  }

  const apiKey = (process.env.FASHN_API_KEY || "").trim();
  if (!apiKey) {
    return json(500, { message: "Missing FASHN_API_KEY in Netlify environment variables." });
  }

  let payload;
  try {
    payload = JSON.parse(event.body || "{}");
  } catch (error) {
    return json(400, { message: "Invalid JSON body." });
  }

  try {
    const response = await fetch(`${FASHN_API_BASE}/run`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });

    const text = await response.text();
    return {
      statusCode: response.status,
      headers: {
        "Content-Type": response.headers.get("content-type") || "application/json; charset=utf-8",
        "Cache-Control": "no-store",
      },
      body: text,
    };
  } catch (error) {
    return json(502, { message: `FASHN proxy request failed: ${error.message}` });
  }
};

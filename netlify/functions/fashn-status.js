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
  if (event.httpMethod !== "GET") {
    return json(405, { message: "Method Not Allowed" });
  }

  const apiKey = (process.env.FASHN_API_KEY || "").trim();
  if (!apiKey) {
    return json(500, { message: "Missing FASHN_API_KEY in Netlify environment variables." });
  }

  const predictionId = (event.queryStringParameters && event.queryStringParameters.id || "").trim();
  if (!predictionId) {
    return json(400, { message: "Missing prediction id." });
  }

  try {
    const response = await fetch(`${FASHN_API_BASE}/status/${encodeURIComponent(predictionId)}`, {
      headers: {
        Authorization: `Bearer ${apiKey}`,
        Accept: "application/json",
      },
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

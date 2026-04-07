const LINE_API = 'https://api.line.me/v2/bot/message/push';

type LineMessage = {
  type: 'text';
  text: string;
};

export async function sendLineMessage(text: string): Promise<void> {
  const token = process.env.LINE_CHANNEL_ACCESS_TOKEN;
  const userId = process.env.LINE_USER_ID;

  if (!token || !userId) {
    console.warn('LINE credentials not configured — skipping notification');
    return;
  }

  const messages: LineMessage[] = [{ type: 'text', text }];

  const res = await fetch(LINE_API, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ to: userId, messages }),
  });

  if (!res.ok) {
    const body = await res.text();
    console.error(`LINE push failed: ${res.status} ${body}`);
  }
}

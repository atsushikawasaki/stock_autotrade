import { NextResponse, type NextRequest } from 'next/server';

const REALM = 'US Auto-Trade Dashboard';

function unauthorized(): NextResponse {
  return new NextResponse('Authentication required', {
    status: 401,
    headers: {
      'WWW-Authenticate': `Basic realm="${REALM}", charset="UTF-8"`,
    },
  });
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let mismatch = 0;
  for (let i = 0; i < a.length; i++) {
    mismatch |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return mismatch === 0;
}

export function proxy(req: NextRequest): NextResponse {
  const expectedUser = process.env.DASHBOARD_USER;
  const expectedPass = process.env.DASHBOARD_PASS;

  if (!expectedUser || !expectedPass) {
    // Auth not configured — fail closed to avoid accidental exposure.
    return new NextResponse('Dashboard auth not configured', { status: 503 });
  }

  const header = req.headers.get('authorization');
  if (!header || !header.toLowerCase().startsWith('basic ')) {
    return unauthorized();
  }

  try {
    const decoded = atob(header.slice(6).trim());
    const sep = decoded.indexOf(':');
    if (sep < 0) return unauthorized();
    const user = decoded.slice(0, sep);
    const pass = decoded.slice(sep + 1);
    if (timingSafeEqual(user, expectedUser) && timingSafeEqual(pass, expectedPass)) {
      return NextResponse.next();
    }
  } catch {
    return unauthorized();
  }

  return unauthorized();
}

export const config = {
  // Protect everything except Next.js internals and static assets.
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)'],
};

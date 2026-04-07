import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY!;

/** Server-side admin client (service role) — use in API routes and cron jobs only */
export const supabaseAdmin = createClient(supabaseUrl, serviceRoleKey);

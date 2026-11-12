-- API access is handled by the FastAPI server using its server-side database role.
-- Public browser roles may read only the published institution/program directory.
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
GRANT SELECT ON TABLE public.directory_institutions, public.directory_programs TO anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  REVOKE ALL ON TABLES FROM anon, authenticated;

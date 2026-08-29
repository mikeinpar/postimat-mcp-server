-- postimat-mcp-server: seed data (FAKE, but realistic)
-- Publication-contour data only. Timestamps are relative to now() so the demo is
-- always "alive": recent publish attempts, recent failures.
-- Loaded automatically by docker-compose after schema.sql.

BEGIN;

-- Explicit ids keep linked rows easy to reference; sequences fixed at the end.

-- ── Channels ─────────────────────────────────────────────────────────────────
-- Two Telegram channels + one MAX channel. Note posting_hours = hours of the day.
-- neuronews: approved & active (publishes). cryptodaily: approved & active.
-- foodie (MAX): approved but is_active=false (user turned it off → won't publish).
INSERT INTO channels
    (id, user_id, tg_chat_id, max_chat_id, title, status, is_active,
     posting_hours, timezone, last_publish_date_hour,
     filter_prompt, generation_prompt, allowed_domains, created_at) VALUES
    (1, 101, -1001111111111, NULL, 'НейроНовости', 'approved', true,
        '{"09:00","13:00","18:00"}', 'Europe/Moscow', to_char(now(), 'YYYY-MM-DD_HH24'),
        'Только про AI, нейросети и ML. Отсекать рекламу и крипту.',
        'Перепиши как краткую новость с эмодзи, до 600 знаков.',
        '{t.me,arxiv.org}', now() - interval '240 days'),
    (2, 102, -1002222222222, NULL, 'Крипта Дейли', 'approved', true,
        '{"08:00","12:00","20:00"}', 'Europe/Moscow', to_char(now() - interval '5 hours', 'YYYY-MM-DD_HH24'),
        'Крипта, биржи, рынки. Без скама и памп-групп.',
        'Сжатый обзор с ключевыми цифрами, нейтральный тон.',
        '{t.me}', now() - interval '400 days'),
    (3, 103, NULL, 5550000001, 'Рецепты за 5 минут', 'approved', false,
        '{"10:00","17:00"}', 'Europe/Moscow', NULL,
        'Только рецепты и еда. Без диет-рекламы.',
        'Дружелюбный тон, список ингредиентов + шаги.',
        '{t.me}', now() - interval '120 days');

-- ── Sources ──────────────────────────────────────────────────────────────────
INSERT INTO sources (channel_id, user_id, source_url, last_processed_id) VALUES
    (1, 101, 'https://t.me/s/ai_source',     1322),
    (1, 101, 'https://t.me/s/ml_digest',      877),
    (2, 102, 'https://t.me/s/crypto_src',     985),
    (2, 102, 'https://t.me/s/markets_feed',   540),
    (3, 103, 'https://t.me/s/food_src',        78);

-- ── posts_queue ──────────────────────────────────────────────────────────────
-- The outcome log. payload mirrors exactly what the workflow logs: the Build
-- Payload item: final_text (post body), title, image_url/video_url, source_id,
-- channel (source), etc. FAILED_PARSER carries {source_url, error}; FAILED_SEND
-- logs the item as-is (the status is the signal, no error field is captured).
INSERT INTO posts_queue
    (id, channel_id, source_url, origin_post_id, published_post_id, status,
     payload, scheduled_time, created_at) VALUES
    -- neuronews: several successes, one skip, one send-failure
    (1, 1, 'https://t.me/s/ai_source', 1301, '100001', 'SUCCESS',
        jsonb_build_object('final_text','GPT-5 держит контекст на миллион токенов — разбираем, что это меняет.',
                           'title','GPT-5: миллион токенов','image_url','https://t.me/s/ai_source/1301.jpg',
                           'video_url','','source_id',12,'channel','ai_source','selected_post_id',1301),
        now() - interval '2 days', now() - interval '2 days'),
    (2, 1, 'https://t.me/s/ml_digest', 861, '100002', 'SUCCESS',
        jsonb_build_object('final_text','Подборка: 7 open-source моделей, которые запускаются на ноутбуке.',
                           'title','7 моделей на ноутбуке','image_url','','video_url','',
                           'source_id',13,'channel','ml_digest','selected_post_id',861),
        now() - interval '1 day' - interval '9 hours', now() - interval '1 day' - interval '9 hours'),
    (3, 1, 'https://t.me/s/ai_source', 1315, '100003', 'SUCCESS',
        jsonb_build_object('final_text','Anthropic выкатили новый инструмент для агентов. Первые впечатления.',
                           'title','Новый инструмент Anthropic','image_url','https://t.me/s/ai_source/1315.jpg',
                           'video_url','','source_id',12,'channel','ai_source','selected_post_id',1315),
        now() - interval '1 day', now() - interval '1 day'),
    (4, 1, 'https://t.me/s/ml_digest', 870, NULL, 'SKIPPED_DUP',
        jsonb_build_object('reason','duplicate of already published source post','selected_post_id',870,
                           'channel','ml_digest'),
        now() - interval '15 hours', now() - interval '15 hours'),
    (5, 1, 'https://t.me/s/ai_source', 1322, NULL, 'FAILED_SEND',
        jsonb_build_object('final_text','Сравнение GPT и Claude на реальных задачах кодинга.',
                           'title','GPT vs Claude','image_url','','video_url','https://t.me/s/ai_source/1322.mp4',
                           'source_id',12,'channel','ai_source','selected_post_id',1322),
        now() - interval '5 hours', now() - interval '5 hours'),
    -- cryptodaily: successes + a parser failure
    (6, 2, 'https://t.me/s/crypto_src', 970, '200001', 'SUCCESS',
        jsonb_build_object('final_text','Биткоин пробил уровень сопротивления — что говорят аналитики.',
                           'title','BTC пробил сопротивление','image_url','https://t.me/s/crypto_src/970.jpg',
                           'video_url','','source_id',14,'channel','crypto_src','selected_post_id',970),
        now() - interval '2 days', now() - interval '2 days'),
    (7, 2, 'https://t.me/s/markets_feed', 533, '200002', 'SUCCESS',
        jsonb_build_object('final_text','Обзор: топ-5 альткоинов с ростом за месяц.',
                           'title','Топ-5 альткоинов','image_url','','video_url','',
                           'source_id',15,'channel','markets_feed','selected_post_id',533),
        now() - interval '1 day', now() - interval '1 day'),
    (8, 2, 'https://t.me/s/crypto_src', 985, '200003', 'SUCCESS',
        jsonb_build_object('final_text','Утренняя сводка по рынку: цены и настроения.',
                           'title','Утренняя сводка','image_url','','video_url','',
                           'source_id',14,'channel','crypto_src','selected_post_id',985),
        now() - interval '5 hours', now() - interval '5 hours'),
    (9, 2, 'https://t.me/s/markets_feed', NULL, NULL, 'FAILED_PARSER',
        jsonb_build_object('source_url','https://t.me/s/markets_feed',
                           'error','Source page returned HTTP 502, parser could not extract posts'),
        now() - interval '18 hours', now() - interval '18 hours'),
    -- foodie (MAX): older successes from before it was turned off
    (10, 3, 'https://t.me/s/food_src', 70, '300001', 'SUCCESS',
        jsonb_build_object('final_text','Паста карбонара за 10 минут — без сливок.',
                           'title','Карбонара за 10 минут','image_url','https://t.me/s/food_src/70.jpg',
                           'video_url','','source_id',16,'channel','food_src','selected_post_id',70),
        now() - interval '6 days', now() - interval '6 days'),
    (11, 3, 'https://t.me/s/food_src', 78, '300002', 'SUCCESS',
        jsonb_build_object('final_text','Три завтрака из яиц, которые не надоедают.',
                           'title','Три завтрака из яиц','image_url','https://t.me/s/food_src/78.jpg',
                           'video_url','','source_id',16,'channel','food_src','selected_post_id',78),
        now() - interval '5 days', now() - interval '5 days');

-- Keep sequences ahead of the explicit ids we inserted.
SELECT setval('channels_id_seq',    (SELECT max(id) FROM channels));
SELECT setval('sources_id_seq',     (SELECT max(id) FROM sources));
SELECT setval('posts_queue_id_seq', (SELECT max(id) FROM posts_queue));

COMMIT;

"""
Tests for discussions course block transformer
"""

from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, BlockFactory

from lms.djangoapps.course_blocks.api import get_course_blocks
from lms.djangoapps.course_blocks.transformers.tests.helpers import TransformerRegistryTestMixin
from openedx.core.djangoapps.discussions.models import (
    DiscussionTopicLink,
    get_default_provider_type,
)
from openedx.core.djangoapps.discussions.transformers import DiscussionsTopicLinkTransformer


class DiscussionsTopicLinkTransformerTestCase(TransformerRegistryTestMixin, ModuleStoreTestCase):
    """
    Tests behaviour of BlockCompletionTransformer
    """
    TRANSFORMER_CLASS_TO_TEST = DiscussionsTopicLinkTransformer

    def setUp(self):
        super().setUp()
        self.test_topic_id = 'test-topic-id'
        self.course = CourseFactory.create()
        section = BlockFactory.create(
            parent_location=self.course.usage_key,
            category="chapter",
        )
        subsection1 = BlockFactory.create(
            parent_location=section.usage_key,
            category="sequential",
        )
        self.discussable_unit = BlockFactory.create(
            parent_location=subsection1.usage_key,
            category="vertical",
            # This won't really be used, but set it anyway
            discussion_enabled=True,
        )
        DiscussionTopicLink.objects.create(
            context_key=self.course.id,
            usage_key=self.discussable_unit.usage_key,
            title=self.discussable_unit.display_name,
            provider_id=get_default_provider_type(),
            external_id=self.test_topic_id,
        )
        self.non_discussable_unit = BlockFactory.create(
            parent_location=subsection1.usage_key,
            category="vertical",
            discussion_enabled=False,
        )

    def test_transform_aggregators(self):
        """
        Tests that a unit that has a discussion topic link created will return the link
        and topic id in the course block data.
        """
        block_structure = get_course_blocks(self.user, self.course.usage_key, self.transformers)

        embed_url = block_structure.get_xblock_field(
            self.discussable_unit.usage_key,
            self.TRANSFORMER_CLASS_TO_TEST.EMBED_URL,
        )
        assert embed_url == f"http://discussions-mfe/{self.course.id}/topics/{self.test_topic_id}"

        external_id = block_structure.get_xblock_field(
            self.discussable_unit.usage_key,
            self.TRANSFORMER_CLASS_TO_TEST.EXTERNAL_ID,
        )
        assert external_id == self.test_topic_id

        embed_url = block_structure.get_xblock_field(
            self.non_discussable_unit.usage_key,
            self.TRANSFORMER_CLASS_TO_TEST.EMBED_URL,
        )
        assert embed_url is None

        external_id = block_structure.get_xblock_field(
            self.non_discussable_unit.usage_key,
            self.TRANSFORMER_CLASS_TO_TEST.EXTERNAL_ID,
        )
        assert external_id is None

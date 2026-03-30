"""
Unit tests for the unit page.
"""


from xmodule.modulestore.django import modulestore
from xmodule.modulestore.tests.factories import BlockFactory
from xmodule.x_module import STUDENT_VIEW

from .utils import StudioPageTestCase


class UnitPageTestCase(StudioPageTestCase):
    """
    Unit tests for the unit page.
    """

    def setUp(self):
        super().setUp()
        self.vertical = BlockFactory.create(parent_location=self.sequential.usage_key,
                                            category='vertical', display_name='Unit')
        self.video = BlockFactory.create(parent_location=self.vertical.usage_key,
                                         category="video", display_name="My Video")
        self.store = modulestore()

    def test_public_component_preview_html(self):
        """
        Verify that a public xblock's preview returns the expected HTML.
        """
        published_video = self.store.publish(self.video.usage_key, self.user.id)  # lint-amnesty, pylint: disable=unused-variable
        self.validate_preview_html(self.video, STUDENT_VIEW, in_unit=True, can_add=False)

    def test_draft_component_preview_html(self):
        """
        Verify that a draft xblock's preview returns the expected HTML.
        """
        self.validate_preview_html(self.video, STUDENT_VIEW, in_unit=True, can_add=False)

    def test_public_child_container_preview_html(self):
        """
        Verify that a public child container rendering on the unit page (which shows a View arrow
        to the container page) returns the expected HTML.
        """
        child_container = BlockFactory.create(parent_location=self.vertical.usage_key,
                                              category='split_test', display_name='Split Test')
        BlockFactory.create(parent_location=child_container.usage_key,
                            category='html', display_name='grandchild')
        published_child_container = self.store.publish(child_container.usage_key, self.user.id)
        self.validate_preview_html(published_child_container, STUDENT_VIEW, in_unit=True, can_add=False)

    def test_draft_child_container_preview_html(self):
        """
        Verify that a draft child container rendering on the unit page (which shows a View arrow
        to the container page) returns the expected HTML.
        """
        child_container = BlockFactory.create(parent_location=self.vertical.usage_key,
                                              category='split_test', display_name='Split Test')
        BlockFactory.create(parent_location=child_container.usage_key,
                            category='html', display_name='grandchild')
        draft_child_container = self.store.get_item(child_container.usage_key)
        self.validate_preview_html(draft_child_container, STUDENT_VIEW, in_unit=True, can_add=False)
